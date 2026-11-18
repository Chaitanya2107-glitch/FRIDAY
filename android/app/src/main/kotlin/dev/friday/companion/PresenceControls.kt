package dev.friday.companion

import android.app.*
import android.content.*
import android.media.AudioManager
import android.os.Build
import androidx.core.app.NotificationCompat
import dev.friday.core.*
import kotlinx.serialization.json.*

/** Phone-side consent is checked again for every signed laptop control message. */
class PresenceControls(private val context: Context) {
    private val prefs = context.getSharedPreferences("presence-controls", Context.MODE_PRIVATE)
    private val repo get() = context.repository
    private val manager get() = context.getSystemService(NotificationManager::class.java)
    private val audio get() = context.getSystemService(AudioManager::class.java)
    @Volatile private var policy: TriagePolicy? = null
    @Volatile private var contact = 0L
    private var recoveryAt = 0.0
    private val now get() = System.currentTimeMillis() / 1000.0
    fun connected() { contact = System.currentTimeMillis() }
    fun connectedNow() = repo.sharingRunning && System.currentTimeMillis() - contact < 45000
    fun triagePolicy(): TriagePolicy? = policy?.takeIf { it.until > now && connectedNow() }
    fun policy(value: JsonObject) { policy = TriagePolicy.parse(value, now); connected(); SignalListener.refresh() }
    fun disconnect() { policy = null; contact = 0; restoreAll() }
    fun canControl() = repo.settings.phoneModes && manager.isNotificationPolicyAccessGranted &&
        !repo.settings.forgetting() && System.currentTimeMillis() >= repo.settings.pausedUntil()
    fun capabilities() = buildJsonObject {
        put("phone_modes", canControl())
        put("notification_snooze", repo.settings.notificationSnooze && repo.collecting("notifications") && SignalListener.connected)
        put("vip", JsonArray((if (repo.collecting("notifications")) repo.settings.vipApps else emptySet()).map(::JsonPrimitive)))
        put("urgent", JsonArray((if (repo.collecting("notifications")) repo.settings.urgentApps else emptySet()).map(::JsonPrimitive)))
    }
    private fun leases() = Json.parseToJsonElement(prefs.getString("modes", "[]")!!).jsonArray.map { value ->
        val v = value.jsonObject
        ModeLease(v.getValue("token").jsonPrimitive.content, v.getValue("mode").jsonPrimitive.content,
            v.getValue("previous").jsonPrimitive.int, v.getValue("applied").jsonPrimitive.int,
            v.getValue("until").jsonPrimitive.double, v["previous_dnd"]?.jsonPrimitive?.intOrNull,
            v["applied_dnd"]?.jsonPrimitive?.intOrNull)
    }
    private fun save(rows: List<ModeLease>) {
        check(prefs.edit().putString("modes", JsonArray(rows.map { row -> buildJsonObject {
            put("token", row.token); put("mode", row.mode); put("previous", row.previous)
            put("applied", row.applied); put("until", row.until)
            row.previousDnd?.let { put("previous_dnd", it) }; row.appliedDnd?.let { put("applied_dnd", it) }
        } }).toString()).commit())
        scheduleRestore(rows.minOfOrNull { it.until })
    }
    private fun current(mode: String) = if (mode == "dnd") manager.currentInterruptionFilter else audio.ringerMode
    private fun apply(mode: String, value: Int) {
        check(manager.isNotificationPolicyAccessGranted)
        if (mode == "dnd") manager.setInterruptionFilter(value) else audio.ringerMode = value
    }
    @Synchronized fun mode(value: JsonObject) {
        val request = ModeRequest.parse(value, now)
        if (request.restore) { restore(request.token, true); return }
        check(canControl() && connectedNow()) { "Enable phone mode control and Android policy access first" }
        val rows = leases().toMutableList()
        val existing = rows.firstOrNull { it.token == request.token }
        if (existing != null) {
            require(existing.mode == request.mode && existing.applied == request.value)
            // Renewal never reapplies a setting the owner manually changed.
            if (current(existing.mode) != existing.applied && !(existing.mode == "dnd" && Build.VERSION.SDK_INT >= 35)) return
            rows.remove(existing); rows += existing.copy(until = request.until); save(rows); return
        }
        check(rows.none { it.mode == request.mode }) { "Another phone rule still owns this mode" }
        val previous = current(request.mode)
        check(previous in if (request.mode == "dnd") 1..4 else 0..2) { "Current phone mode is unavailable" }
        val lease = ModeLease(request.token, request.mode, previous, request.value, request.until, manager.currentInterruptionFilter)
        save(rows + lease) // Record recovery information before the OS effect.
        try {
            apply(request.mode, request.value)
            save(rows + lease.copy(appliedDnd = manager.currentInterruptionFilter))
        }
        catch (failure: Exception) { restore(request.token, true); throw failure }
    }
    @Synchronized private fun restore(token: String, forced: Boolean) {
        val rows = leases()
        val lease = rows.firstOrNull { it.token == token } ?: return
        if (!forced && lease.until > now) return
        if (forced && lease.until > now) save(rows.map { if (it.token == token) it.copy(until = now) else it })
        try {
            val present = current(lease.mode)
            if (lease.mode == "dnd" && Build.VERSION.SDK_INT >= 35) {
                // Android 15+ ALL releases only our app-owned Zen rule.
                apply("dnd", NotificationManager.INTERRUPTION_FILTER_ALL)
            } else if (lease.shouldRestore(now, present, forced) && lease.preservesDnd(manager.currentInterruptionFilter)) {
                apply(lease.mode, lease.previous)
                check(current(lease.mode) == lease.previous) { "Phone mode did not restore" }
            }
            save(rows.filterNot { it.token == token })
        } catch (_: Exception) {
            repo.message = "Phone mode restoration needs Android policy access. Open Presence controls."
            recoveryAt = now + 60
            scheduleRestore(now + 60) // Keep the durable token until restoration is possible.
        }
    }
    @Synchronized fun restoreAll() { leases().forEach { restore(it.token, true) } }
    @Synchronized fun tick() {
        if (policy?.until?.let { it <= now } == true || !connectedNow()) policy = null
        if (now < recoveryAt) return
        if (!repo.sharingRunning || repo.settings.forgetting() || System.currentTimeMillis() < repo.settings.pausedUntil() || !repo.settings.phoneModes) restoreAll()
        else leases().filter { it.until <= now }.forEach { restore(it.token, false) }
    }
    private fun scheduleRestore(until: Double?) {
        val alarm = context.getSystemService(AlarmManager::class.java)
        val pending = PendingIntent.getBroadcast(context, 95,
            Intent(context, ModeRestoreReceiver::class.java).setAction("dev.friday.RESTORE_PHONE_MODES"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        if (until == null) alarm.cancel(pending)
        else alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, maxOf(System.currentTimeMillis() + 1000, (until * 1000).toLong()), pending)
    }
    fun notice(value: JsonObject) {
        require(value.keys.all { it in setOf("text", "kind", "owner", "title") })
        val text = value.getValue("text").jsonPrimitive.content
        require(text.isNotBlank() && text.length <= 2000)
        val kind = value.getValue("kind").jsonPrimitive.content
        require(kind in setOf("presence", "anticipation", "digest", "rule", "triage"))
        if (Build.VERSION.SDK_INT >= 33 && !context.granted(android.Manifest.permission.POST_NOTIFICATIONS)) return
        manager.createNotificationChannel(NotificationChannel("presence", "Presence and reviewed rules", NotificationManager.IMPORTANCE_DEFAULT))
        val owner = value["owner"]?.jsonPrimitive?.content
        require(owner == null || owner.matches(Regex("[A-Za-z0-9_-]{1,80}")))
        val identity = owner?.hashCode() ?: kind.hashCode()
        val open = PendingIntent.getActivity(context, identity, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        manager.notify("presence", identity, NotificationCompat.Builder(context, "presence").setSmallIcon(R.drawable.ic_friday)
            .setContentTitle("FRIDAY").setContentText(text).setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setContentIntent(open).setAutoCancel(true).build())
    }
    fun cancelNotice(value: JsonObject) {
        require(value.keys == setOf("cancel_owner"))
        val owner = value.getValue("cancel_owner").jsonPrimitive.content
        require(owner.matches(Regex("[A-Za-z0-9_-]{1,80}")))
        manager.cancel("presence", owner.hashCode())
    }
    fun forget() { disconnect(); SignalListener.forgetLocal() }
}

class ModeRestoreReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == "dev.friday.RESTORE_PHONE_MODES") context.repository.presence.tick()
    }
}
