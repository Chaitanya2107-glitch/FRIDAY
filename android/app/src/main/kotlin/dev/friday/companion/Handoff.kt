package dev.friday.companion

import android.app.*
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import dev.friday.core.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

class Handoff(private val repo: Repository, private val context: Context) {
    private val db get() = repo.database.handoff()
    fun command(name: String, args: JsonObject) {
        check(repo.settings.paired && !repo.settings.forgetting()) { "Pair first and finish pending deletion" }
        repo.commands.add(name, args)
        SharingService.scheduleSync(context)
        repo.message = "Waiting for laptop. Safe commands expire after 15 minutes."
    }
    suspend fun inbox() {
        val activeContext = currentCoroutineContext()
        fun requireRunning() {
            activeContext.ensureActive()
            check(repo.sharingRunning && !repo.settings.forgetting())
            check(System.currentTimeMillis() >= repo.settings.pausedUntil())
        }
        var backoff = 2000L
        while (currentCoroutineContext().isActive) {
            if (!repo.settings.paired || repo.settings.forgetting() || System.currentTimeMillis() < repo.settings.pausedUntil()) { delay(2000); continue }
            try {
                val messages = repo.client().json("GET", "phone/inbox").body.getValue("messages").jsonArray
                requireRunning()
                repo.presence.connected()
                require(messages.size <= 100)
                val now = System.currentTimeMillis() / 1000.0
                val rows = messages.map { value ->
                    val data = value.jsonObject
                    InboxRow().apply {
                        id = data.getValue("id").jsonPrimitive.content
                        type = data.getValue("type").jsonPrimitive.content
                        payload = data.getValue("payload").jsonObject.toString()
                        created = data.getValue("created").jsonPrimitive.double
                        expiresAt = data.getValue("expires_at").jsonPrimitive.double
                        require(id.matches(Regex("[A-Za-z0-9_-]{16,128}")))
                        require(type in setOf("text", "link", "file", "ring", "approval", "notice", "notice_cancel", "triage_policy", "phone_mode"))
                        require(payload.toByteArray(Charsets.UTF_8).size <= 16000)
                        require(created.isFinite() && expiresAt.isFinite() && expiresAt > created && expiresAt - created <= 86400 && created <= now + 60)
                    }
                }
                repo.database.runInTransaction {
                    requireRunning()
                    rows.forEach { db.receive(it) }
                    db.pruneInbox(now - 86400)
                    requireRunning()
                }
                // Commit receipts before acknowledgement; interrupted notification delivery resumes from Room.
                requireRunning()
                if (rows.isNotEmpty()) repo.client().json("POST", "phone/ack", buildJsonObject { put("ids", JsonArray(rows.map { JsonPrimitive(it.id) })) })
                requireRunning()
                db.inbox().filter { !it.processed && it.expiresAt > now }.forEach { row ->
                    requireRunning()
                    db.processed(row.id)
                    requireRunning()
                    val data = Json.parseToJsonElement(row.payload).jsonObject
                    when (row.type) {
                        "ring" -> Alarm.start(context)
                        "notice" -> repo.presence.notice(data)
                        "notice_cancel" -> repo.presence.cancelNotice(data)
                        "triage_policy" -> repo.presence.policy(data)
                        "phone_mode" -> repo.presence.mode(data)
                        else -> notify(row)
                    }
                }
                backoff = 2000
                if (repo.commands.rows().any { it.state == "waiting" }) repo.synchronize()
                repo.message = "Connected. Inbox uses your laptop only."
                delay(500)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) {
                repo.presence.disconnect()
                repo.message = "Laptop unreachable or request refused. Waiting commands remain on this phone."
                delay(backoff); backoff = (backoff * 2).coerceAtMost(60000)
            }
        }
    }
    private fun notify(row: InboxRow) {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (android.os.Build.VERSION.SDK_INT >= 33 && !context.granted(android.Manifest.permission.POST_NOTIFICATIONS)) return
        val approval = row.type == "approval"
        val channel = if (approval) "approval" else "handoff"
        manager.createNotificationChannel(NotificationChannel(channel, if (approval) "Laptop approvals" else "From your laptop", if (approval) NotificationManager.IMPORTANCE_HIGH else NotificationManager.IMPORTANCE_DEFAULT))
        val intent = PendingIntent.getActivity(context, row.id.hashCode(), Intent(context, HandoffActivity::class.java).putExtra("inbox", row.id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val copy = when (row.type) { "approval" -> "Review this laptop action"; "file" -> "File ready to download"; "link" -> "Link ready to open"; else -> "Note from your laptop" }
        val notification = NotificationCompat.Builder(context, channel).setSmallIcon(R.drawable.ic_friday)
            .setContentTitle(if (approval) "FRIDAY needs your approval" else "FRIDAY handoff")
            .setContentText(copy).setContentIntent(intent).setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setTimeoutAfter(((row.expiresAt * 1000).toLong() - System.currentTimeMillis()).coerceAtLeast(1))
            .addAction(0, if (approval) "Review" else "Open", intent).build()
        manager.notify(row.id.hashCode(), notification)
    }
    fun forget() { Transfers(context, repo).forget() }
}
