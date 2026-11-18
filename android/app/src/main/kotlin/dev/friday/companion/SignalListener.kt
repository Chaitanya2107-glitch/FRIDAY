package dev.friday.companion

import android.content.ComponentName
import android.media.MediaMetadata
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.app.Notification
import android.os.Handler
import android.os.Looper
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import dev.friday.core.*
import kotlinx.serialization.json.*

class SignalListener : NotificationListenerService() {
    private val previousMedia = mutableMapOf<String, String>()
    private val tracked = linkedMapOf<String, NotificationMetadata>()
    private val snoozePolicy = SnoozePolicy()
    private val handler = Handler(Looper.getMainLooper())
    private val snoozed get() = getSharedPreferences("notification-snoozes", MODE_PRIVATE)
    companion object {
        @Volatile var connected = false; private set
        private var instance: SignalListener? = null
        fun refresh() { instance?.let { listener -> listener.handler.post { listener.applyActivePolicy() } } }
        fun forgetLocal() { instance?.let { listener -> listener.handler.post {
            listener.tracked.clear(); listener.snoozed.edit().clear().apply()
        } } }
    }
    override fun onListenerConnected() { connected = true; instance = this; media() }
    override fun onListenerDisconnected() { connected = false; repository.presence.disconnect(); super.onListenerDisconnected() }
    override fun onDestroy() { connected = false; instance = null; tracked.clear(); handler.removeCallbacksAndMessages(null); super.onDestroy() }
    override fun onNotificationPosted(notification: StatusBarNotification) {
        posted(notification, true)
    }
    private fun applyActivePolicy() {
        if (!connected || !repository.collecting("notifications")) { tracked.clear(); return }
        try { activeNotifications?.take(200)?.forEach { posted(it, false) } }
        catch (_: SecurityException) { repository.message = "Notification access is unavailable; snoozing stopped." }
    }
    private fun posted(notification: StatusBarNotification, newEvent: Boolean) {
        val repo = repository
        if (repo.collecting("notifications") && notification.packageName != packageName) {
            val existing = tracked[notification.key]
            val ranking = Ranking()
            val importance = if (currentRanking?.getRanking(notification.key, ranking) == true) ranking.importance.coerceIn(0, 5) else 3
            val initial = existing ?: NotificationMetadata(NotificationSignals.identity(repo.settings.salt, notification.key, notification.postTime),
                safeLabel(notification.packageName, limit = 200), safeLabel(notification.notification.category ?: "unknown"), importance,
                notification.isOngoing || (notification.notification.flags and Notification.FLAG_FOREGROUND_SERVICE) != 0)
            val meta = initial.copy(category = safeLabel(notification.notification.category ?: "unknown"), importance = importance,
                ongoing = notification.isOngoing || (notification.notification.flags and Notification.FLAG_FOREGROUND_SERVICE) != 0)
            if (tracked.size >= 1000 && notification.key !in tracked) tracked.remove(tracked.keys.first())
            tracked[notification.key] = meta.copy(importance = importance)
            val ours = snoozed.getStringSet("ids", emptySet())!!.contains(meta.id)
            if (newEvent && existing == null && !ours) report(meta, "posted", 0, notification.postTime / 1000.0)
            val duration = snoozePolicy.duration(meta.copy(importance = importance), repo.presence.triagePolicy(),
                repo.settings.notificationSnooze, repo.collecting("notifications"), repo.presence.connectedNow(),
                repo.settings.vipApps, repo.settings.urgentApps)
            if (duration != null) {
                // A short OS-owned timer guarantees restoration even if FRIDAY is killed.
                val ids = snoozed.getStringSet("ids", emptySet())!!.toList().takeLast(199).toSet() + meta.id
                if (snoozed.edit().putStringSet("ids", ids).commit()) {
                    try { snoozeNotification(notification.key, duration) }
                    catch (_: SecurityException) { repo.message = "Notification snooze access is unavailable; notifications remain visible." }
                }
            } else if (ours) snoozed.edit().putStringSet("ids", snoozed.getStringSet("ids", emptySet())!!.toSet() - meta.id).apply()
        } else if (!repo.collecting("notifications")) tracked.clear()
        // The local content allowlist never overrides the laptop's metadata-only wire contract.
        // In particular, notification.extras (title/text) is never read.
        media()
    }
    override fun onNotificationRemoved(notification: StatusBarNotification, rankingMap: RankingMap, reason: Int) {
        val repo = repository
        if (!repo.collecting("notifications")) { tracked.clear(); media(); return }
        val meta = tracked[notification.key]
        if (repo.collecting("notifications") && notification.packageName != packageName && meta != null) {
            if (reason != REASON_SNOOZED) {
                report(meta, NotificationSignals.outcome(reason), reason, System.currentTimeMillis() / 1000.0)
                tracked.remove(notification.key)
                snoozed.edit().putStringSet("ids", snoozed.getStringSet("ids", emptySet())!!.toSet() - meta.id).apply()
            }
        } else if (reason != REASON_SNOOZED) tracked.remove(notification.key)
        media()
    }
    private fun report(meta: NotificationMetadata, event: String, reason: Int, time: Double) {
        repository.record("notifications") { buildJsonObject {
            put("package", meta.app); put("time", time); put("category", meta.category)
            put("notification_id", meta.id); put("event", event); put("reason", NotificationSignals.reason(reason))
            put("importance", meta.importance)
        } }
    }
    private fun media() {
        val repo = repository
        if (!repo.collecting("media")) { previousMedia.clear(); return }
        try {
            val controllers = getSystemService(MediaSessionManager::class.java).getActiveSessions(ComponentName(this, SignalListener::class.java))
            controllers.take(5).forEach { controller ->
                if (controller.playbackState?.state != PlaybackState.STATE_PLAYING) { previousMedia.remove(controller.packageName); return@forEach }
                val metadata = controller.metadata ?: return@forEach
                val pkg = controller.packageName
                val title = safeLabel(metadata.getString(MediaMetadata.METADATA_KEY_TITLE) ?: "unknown")
                val artist = safeLabel(metadata.getString(MediaMetadata.METADATA_KEY_ARTIST) ?: "unknown")
                if (previousMedia[pkg] != "$title\u0000$artist") {
                    previousMedia[pkg] = "$title\u0000$artist"
                    repo.record("media") { buildJsonObject { put("package", pkg.take(200)); put("title", title); put("artist", artist) } }
                }
            }
        } catch (_: SecurityException) { repo.message = "Media needs notification-listener access." }
    }
}
