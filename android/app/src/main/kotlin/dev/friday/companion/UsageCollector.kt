package dev.friday.companion

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.os.PowerManager
import android.os.Process
import kotlinx.serialization.json.*

fun Context.hasUsageAccess(): Boolean = getSystemService(AppOpsManager::class.java)
    .unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), packageName) == AppOpsManager.MODE_ALLOWED

class UsageCollector(private val context: Context, private val repo: Repository) {
    private var since = 0L
    private var checked = System.currentTimeMillis()
    private var foreground: String? = null
    @Synchronized fun reset() { foreground = null; since = 0; checked = System.currentTimeMillis() }
    @Synchronized fun screenOff() {
        if (repo.settings.active("app_usage")) flush(System.currentTimeMillis())
        reset()
    }
    private fun flush(end: Long) {
        val pkg = foreground ?: return
        val start = since
        if (end <= start) return
        repo.record("app_usage") {
            val info = runCatching { context.packageManager.getApplicationInfo(pkg, 0) }.getOrNull()
            buildJsonObject {
                put("package", pkg.take(200)); put("label", safeLabel(info?.loadLabel(context.packageManager)?.toString() ?: pkg))
                put("category", info?.category?.coerceIn(-1, 8) ?: -1); put("start", start / 1000.0); put("end", end / 1000.0)
            }
        }
        since = end
    }
    @Synchronized fun poll() {
        if (!repo.settings.active("app_usage") || !context.hasUsageAccess()) { reset(); return }
        if (!context.getSystemService(PowerManager::class.java).isInteractive) { screenOff(); return }
        val now = System.currentTimeMillis()
        val events = context.getSystemService(UsageStatsManager::class.java).queryEvents(checked, now)
        val event = UsageEvents.Event()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.ACTIVITY_RESUMED && event.packageName != foreground) {
                flush(event.timeStamp.coerceAtMost(now)); foreground = event.packageName; since = event.timeStamp.coerceAtLeast(checked)
            } else if (event.eventType == UsageEvents.Event.ACTIVITY_PAUSED && event.packageName == foreground) {
                flush(event.timeStamp.coerceAtMost(now)); foreground = null
            }
        }
        checked = now
        if (foreground != null && now - since >= 300000) flush(now)
    }
}
