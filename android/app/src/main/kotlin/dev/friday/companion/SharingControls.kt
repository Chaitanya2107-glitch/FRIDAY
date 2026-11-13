package dev.friday.companion

import android.content.Intent
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.friday.core.BufferedEvent
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

@Composable fun SharingControls(activity: MainActivity, revision: Int, onChanged: () -> Unit, explain: (String) -> Unit) {
    val repo = activity.repository; val settings = repo.settings; val scope = rememberCoroutineScope()
    var showing by remember { mutableStateOf(false) }; var sent by remember { mutableStateOf(emptyList<BufferedEvent>()) }
    var shownCount by remember { mutableIntStateOf(100) }
    var days by remember { mutableFloatStateOf(settings.retentionDays().toFloat()) }
    var placeName by remember { mutableStateOf("") }; var latitude by remember { mutableStateOf("") }; var longitude by remember { mutableStateOf("") }
    var localStatus by remember { mutableStateOf("") }; var contentPackage by remember { mutableStateOf("") }
    var forgetPrompt by remember { mutableStateOf(false) }; var challenge by remember { mutableStateOf<String?>(null) }
    var pin by remember { mutableStateOf("") }; var busy by remember { mutableStateOf(false) }
    val refresh = revision
    LaunchedEffect(showing, refresh) {
        while (showing) { sent = withContext(Dispatchers.IO) { repo.buffer.sentLastHour() }; delay(5000) }
    }
    HorizontalDivider()
    Text("Phone retention: ${days.toInt()} day(s), at most 5,000 events including sent receipts")
    Slider(value = days, onValueChange = { days = it }, valueRange = 1f..7f, steps = 5, onValueChangeFinished = {
        settings.retention(days.toInt()); scope.launch(Dispatchers.IO) { repo.buffer.prune(settings.retentionDays()) }
    })
    Button(onClick = { showing = !showing }) { Text(if (showing) "Hide Sharing now" else "Sharing now — last hour") }
    if (showing) {
        Text("Only laptop-acknowledged events are shown, with their exact sent payload. Pending events are not presented as sent.")
        if (sent.isEmpty()) Text("No acknowledged events in the last hour.")
        sent.asReversed().take(shownCount).forEach { row ->
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) {
                Text("${row.event.type} · sent ${java.util.Date(row.sentAt)}")
                Text("Observed ${java.util.Date((row.event.timestamp * 1000).toLong())}")
                Text(row.event.payload.toString(), style = MaterialTheme.typography.bodySmall)
            } }
        }
        if (sent.size > shownCount) TextButton(onClick = { shownCount += 100 }) { Text("Show next 100 (${shownCount} of ${sent.size} shown)") }
    }
    OutlinedButton(onClick = { scope.launch { repo.synchronize(); localStatus = repo.message } }) { Text("Sync pending events now") }
    OutlinedButton(onClick = {
        runCatching { CustomTabsIntent.Builder().build().launchUrl(activity, android.net.Uri.parse(settings.origin + "/app/")) }
            .onFailure { localStatus = "No browser supports opening the PWA." }
    }) { Text("Open FRIDAY PWA") }
    if (settings.enabled("places")) {
        Text("Named places — coordinates stay on this phone", style = MaterialTheme.typography.titleMedium)
        Text("Enter coordinates from your own map. FRIDAY does not read GPS samples. Use at least a 100 m radius; callbacks can be delayed by Android.")
        OutlinedTextField(placeName, { placeName = it.take(60) }, label = { Text("Name, e.g. home, college, library") })
        OutlinedTextField(latitude, { latitude = it }, label = { Text("Latitude (phone-only configuration)") })
        OutlinedTextField(longitude, { longitude = it }, label = { Text("Longitude (phone-only configuration)") })
        Button(onClick = {
            val lat = latitude.toDoubleOrNull(); val lon = longitude.toDoubleOrNull(); val name = safeLabel(placeName.trim(), "", 60)
            if (lat == null || lon == null || !lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0 || name.isBlank()) localStatus = "Enter a name and valid coordinates."
            else {
                val rows = settings.places.filter { it.jsonObject.getValue("name").jsonPrimitive.content != name }
                if (rows.size >= 20) localStatus = "At most 20 named places." else {
                    settings.places = JsonArray(rows + buildJsonObject { put("name", name); put("latitude", lat); put("longitude", lon); put("radius", 150) })
                    latitude = ""; longitude = ""; placeName = ""; localStatus = "Place stored only on this phone."; onChanged()
                }
            }
        }) { Text("Save local geofence (150 m)") }
        settings.places.forEach { place ->
            val name = place.jsonObject.getValue("name").jsonPrimitive.content
            TextButton(onClick = { settings.places = JsonArray(settings.places.filter { it != place }); onChanged() }) { Text("Remove $name") }
        }
    }
    if (settings.enabled("notifications")) {
        Text("Local content preference list: ${settings.contentApps.sorted().joinToString().ifBlank { "empty" }}")
        Text("The current laptop receiver accepts metadata only. This local list never enables title/text transmission; FRIDAY does not read those fields.")
        OutlinedTextField(contentPackage, { contentPackage = it.take(200) }, label = { Text("Package for local allow-content preference") })
        TextButton(onClick = {
            if (contentPackage.matches(Regex("[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+"))) {
                settings.contentApps = settings.contentApps + contentPackage; contentPackage = ""; onChanged()
            }
        }) { Text("Add local preference") }
        if (settings.contentApps.isNotEmpty()) TextButton(onClick = { settings.contentApps = emptySet(); onChanged() }) { Text("Clear local content list") }
    }
    Button(enabled = !busy, onClick = { forgetPrompt = true }) { Text("Forget phone data") }
    suspend fun requestChallenge() {
        busy = true
        try {
            val reply = repo.forgetChallenge()
            require(reply.getValue("result").jsonPrimitive.content == "approval_required")
            challenge = reply.getValue("challenge").jsonPrimitive.content
        } catch (_: Exception) { localStatus = "Phone buffer is wiped. Laptop deletion is pending: reconnect and retry approval." }
        finally { busy = false }
    }
    if (settings.forgetting()) OutlinedButton(enabled = !busy, onClick = { scope.launch { requestChallenge() } }) { Text("Retry pending laptop deletion") }
    Text(localStatus)
    if (forgetPrompt) AlertDialog(onDismissRequest = { forgetPrompt = false }, title = { Text("Forget this phone’s data?") },
        text = { Text("This immediately stops sharing and deletes all queued and sent records on the phone. It then requests a PIN-confirmed deletion on the laptop. If offline, deletion remains visibly pending and uploads stay blocked. Named places and home-network settings are also cleared.") },
        confirmButton = { TextButton(onClick = {
            forgetPrompt = false
            scope.launch {
                repo.beginForget(); settings.places = JsonArray(emptyList()); settings.homeHash = ""; settings.contentApps = emptySet()
                activity.stopService(Intent(activity, SharingService::class.java)); onChanged(); requestChallenge()
            }
        }) { Text("Wipe phone and request laptop deletion") } }, dismissButton = { TextButton(onClick = { forgetPrompt = false }) { Text("Cancel") } })
    if (challenge != null) AlertDialog(onDismissRequest = { challenge = null; pin = "" }, title = { Text("Approve laptop deletion") },
        text = { Column { Text("Enter the pairing PIN. Challenge lasts 60 seconds. Three wrong PIN attempts lock approvals for 10 minutes.")
            OutlinedTextField(pin, { pin = it.filter(Char::isDigit).take(6) }, visualTransformation = PasswordVisualTransformation(), label = { Text("6-digit PIN") }) } },
        confirmButton = { TextButton(enabled = pin.matches(Regex("[0-9]{6}")) && !busy, onClick = {
            val current = challenge!!; val entered = pin; pin = ""; challenge = null
            scope.launch {
                busy = true
                try { repo.approveForget(current, entered); localStatus = repo.message; onChanged() }
                catch (_: Exception) { localStatus = "Approval refused or expired. Laptop deletion remains pending; request a new challenge. After three bad PINs, wait 10 minutes." }
                finally { busy = false }
            }
        }) { Text("Approve once") } }, dismissButton = { TextButton(onClick = { challenge = null; pin = "" }) { Text("Keep pending") } })
}
