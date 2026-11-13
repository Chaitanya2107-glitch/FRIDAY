package dev.friday.companion

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings as AndroidSettings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import kotlinx.coroutines.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFFFB347), background = Color(0xFF101115))) {
            Surface(Modifier.fillMaxSize()) { CompanionScreen(this) }
        } }
    }
}

@Composable private fun CompanionScreen(activity: MainActivity) {
    val repo = activity.repository; val settings = repo.settings; val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var paired by remember { mutableStateOf(settings.paired) }; var revision by remember { mutableIntStateOf(0) }
    var explanation by remember { mutableStateOf<String?>(null) }; var pending by remember { mutableStateOf<String?>(null) }
    var pendingSpecial by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf(repo.message) }
    fun start() {
        if (Build.VERSION.SDK_INT >= 33 && !activity.granted(Manifest.permission.POST_NOTIFICATIONS)) explanation = "persistent"
        else SharingService.start(activity)
    }
    fun enable(signal: String) {
        if (settings.forgetting()) { status = "Finish laptop deletion before re-enabling signals."; return }
        settings.toggle(signal, true); revision++; start()
        if (signal in setOf("sleep", "steps")) scope.launch(Dispatchers.IO) { AdvancedSignals(activity, repo).health(false) }
    }
    val special = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        val signal = pendingSpecial; pendingSpecial = null
        val allowed = when (signal) {
            "app_usage" -> activity.hasUsageAccess()
            "media", "notifications" -> NotificationManagerCompat.getEnabledListenerPackages(activity).contains(activity.packageName)
            "places" -> activity.granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            else -> false
        }
        if (signal != null && allowed) enable(signal) else status = "Access was not enabled. The signal stays off."
    }
    val health = rememberLauncherForActivityResult(PermissionController.createRequestPermissionResultContract()) { permissions ->
        val signal = pending; pending = null
        val needed = if (signal == "sleep") HealthPermission.getReadPermission(SleepSessionRecord::class) else HealthPermission.getReadPermission(StepsRecord::class)
        if (signal in setOf("sleep", "steps") && needed in permissions) enable(signal!!) else if (signal == "health_background") status = "Health background-read preference updated." else status = "Health read permission denied; signal stays off."
    }
    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { results ->
        val signal = pending; pending = null
        if (signal == "persistent") {
            if (activity.granted(Manifest.permission.POST_NOTIFICATIONS)) SharingService.start(activity)
            else { settings.enabledSignals().forEach { settings.toggle(it, false) }; revision++; status = "Signals remain off because the sharing notification was denied." }
        } else if (signal == "wifi_identity") status = if (activity.granted(Manifest.permission.ACCESS_FINE_LOCATION)) "Now tap ‘Remember current Wi-Fi as home’." else "Network type works without a Wi-Fi name/hash."
        else if (signal == "places" && activity.granted(Manifest.permission.ACCESS_FINE_LOCATION)) explanation = "places_background"
        else if (signal != null && results.values.all { it }) enable(signal) else status = "Permission denied; signal stays off."
    }
    fun requestSignal(signal: String) {
        when (signal) {
            "app_usage" -> { pendingSpecial = signal; special.launch(Intent(AndroidSettings.ACTION_USAGE_ACCESS_SETTINGS, Uri.parse("package:${activity.packageName}"))) }
            "media", "notifications" -> { pendingSpecial = signal; special.launch(Intent(AndroidSettings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
            "motion" -> { pending = signal; permissions.launch(arrayOf(Manifest.permission.ACTIVITY_RECOGNITION)) }
            "places" -> { pending = signal; permissions.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)) }
            "audio_devices" -> if (Build.VERSION.SDK_INT >= 31) { pending = signal; permissions.launch(arrayOf(Manifest.permission.BLUETOOTH_CONNECT)) } else enable(signal)
            "sleep", "steps" -> {
                if (HealthConnectClient.getSdkStatus(activity) != HealthConnectClient.SDK_AVAILABLE) status = "Health Connect is not available. Install/open it on this phone first."
                else { pending = signal; health.launch(setOf(if (signal == "sleep") HealthPermission.getReadPermission(SleepSessionRecord::class) else HealthPermission.getReadPermission(StepsRecord::class))) }
            }
            else -> enable(signal)
        }
    }
    LaunchedEffect(Unit) { while (true) { status = repo.message; delay(2000) } }
    LaunchedEffect(lifecycle) { lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
        while (true) { withContext(Dispatchers.IO) { AdvancedSignals(activity, repo).health(false) }; delay(300000) }
    } }
    Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("FRIDAY · companion", style = MaterialTheme.typography.headlineMedium)
        Text("Your phone. Your laptop. Your choice.")
        if (!paired) PairingUi(activity) { paired = true }
        else {
            Text(status)
            if (System.currentTimeMillis() < settings.pausedUntil()) Text("Everything is paused for up to one hour. Buffered events will not upload during the pause.")
            explanations.forEach { (signal, copy) ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(copy.name, Modifier.weight(1f))
                    Switch(checked = settings.enabled(signal).also { revision }, onCheckedChange = { on ->
                        if (on) explanation = signal else {
                            settings.toggle(signal, false); revision++
                            scope.launch(Dispatchers.IO) { repo.buffer.discardSignal(signal) }
                            if (settings.enabledSignals().isEmpty()) activity.stopService(Intent(activity, SharingService::class.java)) else start()
                        }
                    })
                }
            }
            Button(onClick = { settings.pauseHour(); revision++; start() }) { Text("Pause everything for 1 hour") }
            OutlinedButton(onClick = { settings.resume(); revision++; start() }) { Text("Resume sharing / restart service") }
            OutlinedButton(onClick = { explanation = "battery_exemption" }) { Text("Explain battery optimisation exemption") }
            if (settings.enabled("network")) {
                OutlinedButton(onClick = {
                    if (!activity.granted(Manifest.permission.ACCESS_FINE_LOCATION)) explanation = "wifi_identity"
                    else {
                        val hash = SystemSignals.ssidHash(activity)
                        if (hash != null) { settings.homeHash = hash; status = "Salted home Wi-Fi hash saved. No Wi-Fi name stored." } else status = "Wi-Fi identity unavailable. Connect Wi-Fi and enable Location on the phone."
                    }
                }) { Text("Remember current Wi-Fi as home") }
            }
            if (settings.enabled("sleep") || settings.enabled("steps")) OutlinedButton(onClick = { explanation = "health_background" }) { Text("Optional background Health aggregates") }
            SharingControls(activity, revision, onChanged = { revision++; start() }, explain = { explanation = it })
        }
    }
    if (explanation != null) {
        val key = explanation!!
        val copy = explanations[key] ?: when (key) {
            "persistent" -> Explanation("Visible sharing notification", "FRIDAY needs notification permission to keep sharing visible. If denied, collection stays off. You can stop sharing from the app.")
            "places_background" -> Explanation("Allow places in the background", "On the next Android Settings screen choose Location → Allow all the time. This is needed for named enter/leave geofences while the app is closed. Coordinates stay on the phone. If you decline, places stays off.")
            "wifi_identity" -> Explanation("Optional home Wi-Fi identity", "Android treats SSID access as location access. The next prompt asks for precise Location solely to recognise your chosen home network. FRIDAY hashes the SSID with a phone-only salt and never stores/sends its name. Network type sharing works without this.")
            "health_background" -> Explanation("Optional background health reads", "Only if Health Connect supports it, allow read-only daily sleep/step aggregates while FRIDAY is not visible. Without it, collection happens while this screen is open. No health-write access is requested.")
            else -> Explanation("Battery optimisation", "Android may stop background sharing. You can explicitly exempt FRIDAY on the next screen for more reliable collection. This uses more battery. Declining is fine; WorkManager retries pending events and Android/OEM scheduling can still delay work.")
        }
        AlertDialog(onDismissRequest = { explanation = null }, title = { Text(copy.name) }, text = { Text(copy.text) },
            confirmButton = { TextButton(onClick = {
                explanation = null
                when (key) {
                    "persistent" -> if (Build.VERSION.SDK_INT >= 33) { pending = key; permissions.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS)) } else SharingService.start(activity)
                    "places_background" -> { pendingSpecial = "places"; special.launch(Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${activity.packageName}"))) }
                    "wifi_identity" -> { pending = key; permissions.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)) }
                    "health_background" -> {
                        if (HealthConnectClient.getSdkStatus(activity) == HealthConnectClient.SDK_AVAILABLE &&
                            HealthConnectClient.getOrCreate(activity).features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE) {
                            pending = key; health.launch(setOf(HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND))
                        } else status = "Background Health reads are unsupported here. Enabled aggregates refresh while the app is visible."
                    }
                    "battery_exemption" -> activity.startActivity(Intent(AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${activity.packageName}")))
                    else -> requestSignal(key)
                }
            }) { Text("Continue") } }, dismissButton = { TextButton(onClick = { explanation = null }) { Text("Cancel") } })
    }
}
