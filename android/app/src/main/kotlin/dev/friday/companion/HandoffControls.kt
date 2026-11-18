package dev.friday.companion

import android.content.Intent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import dev.friday.core.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

@Composable fun HandoffControls(activity: MainActivity, startConnection: () -> Unit) {
    val repo = activity.repository; val scope = rememberCoroutineScope()
    var connection by remember { mutableStateOf(repo.settings.connection) }
    var waiting by remember { mutableStateOf(emptyList<WaitingCommand>()) }
    var files by remember { mutableStateOf(emptyList<JsonObject>()) }
    var note by remember { mutableStateOf("") }; var status by remember { mutableStateOf("") }
    var enrollment by remember { mutableStateOf(false) }; var busy by remember { mutableStateOf(false) }
    var enrolled by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            withContext(Dispatchers.IO) { waiting = repo.commands.rows(); files = Transfers(activity, repo).waiting() }
            connection = repo.settings.connection
            delay(2000)
        }
    }
    HorizontalDivider()
    Text("Handoff and approvals", style = MaterialTheme.typography.titleLarge)
    Text("Signals already keep their visible connection running. This switch keeps it running when signals are off. No clipboard is read in the background.")
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text("Keep connection with signals off", Modifier.weight(1f))
        Switch(checked = connection, enabled = !repo.settings.forgetting(), onCheckedChange = { on ->
            connection = on; repo.settings.connection = on
            if (on) startConnection()
            else if (repo.settings.enabledSignals().isEmpty()) activity.stopService(Intent(activity, SharingService::class.java))
        })
    }
    OutlinedButton(onClick = { activity.startActivity(Intent(activity, ShareActivity::class.java).setAction("dev.friday.CLIPBOARD")) }) { Text("Review and send current clipboard") }
    OutlinedTextField(note, { note = it.take(4000) }, label = { Text("Note or link for the laptop") }, modifier = Modifier.fillMaxWidth())
    fun enqueue(command: String, args: JsonObject) {
        scope.launch {
            try {
                withContext(Dispatchers.IO) { repo.handoff.command(command, args) }
                note = ""; status = "Waiting for laptop. Safe commands expire after 15 minutes."
                repo.synchronize()
            } catch (_: Exception) { status = "Could not queue this action. Pair first or finish pending deletion." }
        }
    }
    Button(enabled = note.isNotBlank() && !repo.settings.forgetting(), onClick = { enqueue("phone_handoff", buildJsonObject { put("text", note) }) }) { Text("Send note or link") }
    OutlinedButton(enabled = !repo.settings.forgetting(), onClick = { enqueue("ring_laptop", buildJsonObject {}) }) { Text("Ring my laptop") }
    Text("Waiting and receipts", style = MaterialTheme.typography.titleMedium)
    Text("Only safe actions wait. Confirm-risk actions never enter this queue. An uncertain receipt is never retried.")
    if (waiting.isEmpty() && files.isEmpty()) Text("Nothing is waiting.")
    waiting.forEach { row ->
        Text("${row.command.replace('_', ' ')} · ${row.state} · expires ${java.util.Date((row.expiresAt * 1000).toLong())}")
        if (row.command == "ring_laptop" && row.state == "completed") {
            val app = (row.reply["last_active_app"] ?: row.reply["app"] ?: row.reply["current_app"])?.jsonPrimitive?.contentOrNull ?: "unknown"
            val idle = (row.reply["idle_seconds"] ?: row.reply["idle"])?.jsonPrimitive?.doubleOrNull
            Text("Laptop's last active app: $app. " + if (idle == null) "Idle time unavailable." else "Idle for ${idle.toInt()} seconds.")
        }
        TextButton(onClick = { scope.launch(Dispatchers.IO) { repo.commands.dismiss(row.id) } }) { Text(if (row.state == "waiting") "Cancel waiting action" else "Dismiss receipt") }
    }
    files.forEach { row ->
        Text("${row.getValue("name").jsonPrimitive.content} · file waiting · ${row.getValue("offset").jsonPrimitive.content}/${row.getValue("size").jsonPrimitive.content} bytes")
        TextButton(onClick = { scope.launch(Dispatchers.IO) { Transfers(activity, repo).remove(row.getValue("local").jsonPrimitive.content) } }) { Text("Remove waiting file") }
    }
    Text("Files use Android's Share button. They are copied into a private buffer, capped at 100 MB and expire after 24 hours. Large transfers can take hours under P0's unchanged rate limit.")
    OutlinedButton(enabled = !busy, onClick = { enrollment = true }) { Text("Set up phone approvals") }
    OutlinedButton(enabled = !busy, onClick = {
        busy = true
        scope.launch {
            try {
                val response = withContext(Dispatchers.IO) { repo.client().json("GET", "phone/approval/key").body }
                enrolled = response["registered"]?.jsonPrimitive?.boolean == true
                status = if (enrolled) "Approval key registered. Enable the optional second factor on your laptop." else "No approval key is registered. Start setup and approve the laptop prompt."
            } catch (_: Exception) { status = "Laptop unavailable. You can still confirm actions on the laptop." }
            finally { busy = false }
        }
    }) { Text("Check approval setup") }
    Text(status)
    if (enrollment) AlertDialog(onDismissRequest = { enrollment = false }, title = { Text("Set up strong biometric approvals?") },
        text = { Text("FRIDAY creates a separate nonexportable Android Keystore key. Setup replaces an earlier phone approval key; approve the new key on the laptop before using it. Each approval requires a fresh strong fingerprint or face scan. This is optional; the laptop prompt remains available. It never unlocks Windows. Enable a strong biometric in Android Settings first.") },
        confirmButton = { TextButton(onClick = {
            enrollment = false; busy = true
            scope.launch {
                try {
                    withContext(Dispatchers.IO) { repo.client().json("POST", "phone/approval/enroll", buildJsonObject { put("public_key", ApprovalKey(activity).renewForEnrollment()) }) }
                    status = "Approve this phone's approval key on the laptop, then tap Check approval setup."
                } catch (_: Exception) { status = "Could not enroll. Check the laptop connection and strong biometric enrollment; the local laptop prompt still works." }
                finally { busy = false }
            }
        }) { Text("Create key and ask laptop") } }, dismissButton = { TextButton(onClick = { enrollment = false }) { Text("Cancel") } })
}
