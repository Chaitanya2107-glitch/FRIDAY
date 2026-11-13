package dev.friday.companion

import android.content.ComponentName
import android.media.MediaMetadata
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlinx.serialization.json.*

class SignalListener : NotificationListenerService() {
    private val previousMedia = mutableMapOf<String, String>()
    override fun onListenerConnected() { media() }
    override fun onNotificationPosted(notification: StatusBarNotification) {
        val repo = repository
        if (repo.collecting("notifications") && notification.packageName != packageName) {
            repo.record("notifications") { buildJsonObject {
                put("package", safeLabel(notification.packageName, limit = 200)); put("time", notification.postTime / 1000.0)
                put("category", safeLabel(notification.notification.category ?: "unknown"))
            } }
        }
        // The local content allowlist never overrides the laptop's metadata-only wire contract.
        // In particular, notification.extras (title/text) is never read.
        media()
    }
    override fun onNotificationRemoved(notification: StatusBarNotification) { media() }
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
