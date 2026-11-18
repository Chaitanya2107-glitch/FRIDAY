package dev.friday.companion

import android.app.NotificationManager
import android.content.Intent
import android.provider.Settings as AndroidSettings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.core.app.NotificationManagerCompat
import dev.friday.core.TriagePolicy

@Composable fun PresenceSettings(activity: MainActivity) {
    val repo = activity.repository; val settings = repo.settings
    var modes by remember { mutableStateOf(settings.phoneModes) }
    var snooze by remember { mutableStateOf(settings.notificationSnooze) }
    var prompt by remember { mutableStateOf<String?>(null) }
    var pending by remember { mutableStateOf<String?>(null) }
    var message by remember { mutableStateOf("") }
    var app by remember { mutableStateOf("") }
    var vip by remember { mutableStateOf(settings.vipApps) }
    var urgent by remember { mutableStateOf(settings.urgentApps) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        when (pending) {
            "modes" -> {
                modes = activity.getSystemService(NotificationManager::class.java).isNotificationPolicyAccessGranted
                settings.phoneModes = modes
                message = if (modes) "Reviewed laptop rules may control this phone. You can switch access off here." else "Android policy access was not granted. Phone mode control remains off."
            }
            "snooze" -> {
                snooze = NotificationManagerCompat.getEnabledListenerPackages(activity).contains(activity.packageName)
                settings.notificationSnooze = snooze
                message = if (snooze) "Snoozing still requires Notification metadata sharing and a fresh signed focus policy." else "Notification access was not granted. Snoozing remains off."
            }
        }
        pending = null
    }
    HorizontalDivider()
    Text("Presence controls", style = MaterialTheme.typography.titleLarge)
    Text("Laptop rules must be reviewed there first. These separate phone permissions start off and never enable signal collection.")
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text("Allow reviewed DND / ringer changes", Modifier.weight(1f))
        Switch(checked = modes, enabled = !settings.forgetting(), onCheckedChange = { on ->
            if (on) prompt = "modes"
            else { repo.presence.restoreAll(); modes = false; settings.phoneModes = false }
        })
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text("Snooze low-score notifications in focus", Modifier.weight(1f))
        Switch(checked = snooze, enabled = !settings.forgetting(), onCheckedChange = { on ->
            if (on) prompt = "snooze"
            else { snooze = false; settings.notificationSnooze = false; message = "No snoozes will renew. Existing snoozes return within 10 seconds." }
        })
    }
    Text("Snoozes last at most 10 seconds and renew only during an approved focus policy. At its end, or when paused/disconnected, Android restores them within 10 seconds. Calls, alarms, important/ongoing notifications and your VIP/urgent apps always pass. FRIDAY never cancels or reposts another app's notification.")
    Text("VIP and urgent apps", style = MaterialTheme.typography.titleMedium)
    Text("Use the package shown in Sharing now, for example com.whatsapp. These lists start empty and never allow notification content.")
    OutlinedTextField(app, { app = it.take(200) }, modifier = Modifier.fillMaxWidth(), label = { Text("App package") }, singleLine = true)
    fun add(isVip: Boolean) {
        try {
            val value = app.trim(); TriagePolicy.packageName(value)
            if (isVip) { settings.vipApps = vip + value; vip = settings.vipApps }
            else { settings.urgentApps = urgent + value; urgent = settings.urgentApps }
            app = ""; message = "Saved on this phone. The next heartbeat updates laptop triage."
        } catch (_: IllegalArgumentException) { message = "Use a valid app package. Each list holds at most 10 apps." }
    }
    Row { TextButton(onClick = { add(true) }) { Text("Add VIP") }; TextButton(onClick = { add(false) }) { Text("Add urgent") } }
    vip.forEach { value -> TextButton(onClick = { settings.vipApps = vip - value; vip = settings.vipApps }) { Text("Remove VIP: $value") } }
    urgent.forEach { value -> TextButton(onClick = { settings.urgentApps = urgent - value; urgent = settings.urgentApps }) { Text("Remove urgent: $value") } }
    OutlinedButton(onClick = { repo.presence.restoreAll(); message = repo.message }) { Text("Restore phone modes now") }
    Text(message)
    if (prompt != null) {
        val type = prompt!!
        AlertDialog(onDismissRequest = { prompt = null }, title = { Text(if (type == "modes") "Allow DND and ringer control?" else "Allow temporary notification snoozes?") },
            text = { Text(if (type == "modes")
                "The next Android screen grants Notification policy access. Only rules you confirmed on the laptop may change DND/ringer settings. A durable receipt restores the prior mode on exit, undo, pause or expiry while preserving manual changes. Android 15+ keeps FRIDAY's DND rule separate from your own. Android scheduling or permission revocation can delay recovery; Restore phone modes now is available. This never unlocks your phone or Windows."
                else "Notification-listener access is powerful. FRIDAY reads metadata only: package, category, importance and open/dismiss removal reason; no title, text or extras. This optional setting snoozes only low-score apps selected by the laptop during focus, never VIP/call/alarm/ongoing notifications. Android restores timed snoozes within 10 seconds after the policy ends. Notification metadata sharing remains a separate toggle.") },
            confirmButton = { TextButton(onClick = {
                prompt = null
                if (type == "modes") {
                    if (activity.getSystemService(NotificationManager::class.java).isNotificationPolicyAccessGranted) {
                        modes = true; settings.phoneModes = true
                    } else { pending = type; permission.launch(Intent(AndroidSettings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)) }
                } else {
                    if (NotificationManagerCompat.getEnabledListenerPackages(activity).contains(activity.packageName)) {
                        snooze = true; settings.notificationSnooze = true
                    } else { pending = type; permission.launch(Intent(AndroidSettings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
                }
            }) { Text("Continue") } }, dismissButton = { TextButton(onClick = { prompt = null }) { Text("Cancel") } })
    }
}
