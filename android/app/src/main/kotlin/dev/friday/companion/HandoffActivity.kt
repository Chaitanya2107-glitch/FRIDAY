package dev.friday.companion

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import dev.friday.core.TransferRules
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

class HandoffActivity : ComponentActivity() {
    private var authentication: CancellationSignal? = null
    override fun onDestroy() { authentication?.cancel(); super.onDestroy() }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val identity = intent.getStringExtra("inbox").orEmpty()
        setContent { MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFFFB347))) { Surface(Modifier.fillMaxSize()) {
            var row by remember { mutableStateOf<InboxRow?>(null) }; var loaded by remember { mutableStateOf(false) }
            var status by remember { mutableStateOf("") }; var busy by remember { mutableStateOf(false) }
            var answered by remember { mutableStateOf(false) }; val scope = rememberCoroutineScope()
            LaunchedEffect(identity) { row = withContext(Dispatchers.IO) { repository.database.handoff().inbox(identity) }; loaded = true }
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("From your laptop", style = MaterialTheme.typography.headlineMedium)
                val message = row
                val expired = message != null && message.expiresAt <= System.currentTimeMillis() / 1000.0
                if (!loaded) Text("Loading saved message…")
                else if (message == null || expired || repository.settings.forgetting()) Text("This message expired or was removed. Request a fresh handoff on your laptop.")
                else {
                    val data = remember(message.payload) { Json.parseToJsonElement(message.payload).jsonObject }
                    when (message.type) {
                        "text" -> {
                            Text(data["text"]?.jsonPrimitive?.content.orEmpty())
                            Text("This note is displayed locally. It has not changed your clipboard.")
                            OutlinedButton(onClick = {
                                getSystemService(android.content.ClipboardManager::class.java).setPrimaryClip(android.content.ClipData.newPlainText("FRIDAY", data["text"]?.jsonPrimitive?.content.orEmpty()))
                                status = "Copied to this phone's clipboard."
                            }) { Text("Copy note") }
                        }
                        "link" -> {
                            val link = data["url"]?.jsonPrimitive?.content ?: data["text"]?.jsonPrimitive?.content.orEmpty()
                            Text(link)
                            Button(enabled = TransferRules.link(link) != null, onClick = {
                                runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(TransferRules.link(link)!!)).addCategory(Intent.CATEGORY_BROWSABLE)) }
                                    .onFailure { status = "No browser could open this link." }
                            }) { Text("Open link in browser") }
                        }
                        "file" -> {
                            Text(data["name"]?.jsonPrimitive?.content.orEmpty())
                            Text("Download to Downloads/FRIDAY. The file will not be opened. Large files take time under P0's rate limits.")
                            Button(enabled = !busy && !answered, onClick = {
                                busy = true
                                scope.launch {
                                    try {
                                        withContext(Dispatchers.IO) { Transfers(this@HandoffActivity, repository).download(data) }
                                        answered = true; status = "Saved to Downloads/FRIDAY. Open it yourself from Files when ready."
                                    } catch (_: Exception) { status = "Download failed or expired. Partial file removed; reconnect and retry." }
                                    finally { busy = false }
                                }
                            }) { Text(if (busy) "Downloading…" else "Download file") }
                        }
                        "approval" -> {
                            val action = data.getValue("action").jsonPrimitive.content
                            val summary = data.getValue("summary").jsonPrimitive.content
                            Text("Laptop asks to ${action.replace('_', ' ')}", style = MaterialTheme.typography.titleLarge)
                            Text(summary)
                            Text("Approve only if you started this action. A fresh strong biometric signs this exact request; approval expires after one minute.")
                            val permitted = action in setOf("delete_files", "send_message", "change_settings")
                            fun reply(accepted: Boolean, signature: String) {
                                if (answered) return
                                answered = true; busy = true
                                scope.launch {
                                    try {
                                        require(message.expiresAt > System.currentTimeMillis() / 1000.0)
                                        withContext(Dispatchers.IO) { repository.client().json("POST", "phone/approval/result", buildJsonObject {
                                            put("challenge", data.getValue("challenge")); put("accepted", accepted); put("signature", signature)
                                        }) }
                                        status = if (accepted) "Approval sent once." else "Denied."
                                    } catch (_: Exception) { status = "Laptop did not confirm this response. It will time out; use the laptop prompt." }
                                    finally { busy = false }
                                }
                            }
                            Button(enabled = permitted && !busy && !answered, onClick = {
                                if (message.expiresAt <= System.currentTimeMillis() / 1000.0) { status = "Expired. Use the laptop prompt."; return@Button }
                                busy = true
                                runCatching {
                                    val canonical = data.getValue("canonical").jsonPrimitive.content
                                    val fields = canonical.split('\n')
                                    require(fields.size == 6 && fields[0] == "FRIDAY-PHONE-APPROVAL-v1" && fields[1] == repository.key.id)
                                    require(fields[2] == data.getValue("challenge").jsonPrimitive.content && fields[3] == action)
                                    require(fields[4].matches(Regex("[a-f0-9]{64}")) && fields[5].toLong() == data.getValue("expires_at").jsonPrimitive.double.toLong())
                                    authentication = ApprovalKey(this@HandoffActivity).approve(this@HandoffActivity,
                                        canonical, summary) { signature ->
                                        busy = false
                                        if (signature == null) reply(false, "") else reply(true, signature)
                                    }
                                }.onFailure { busy = false; status = "Strong biometric unavailable. Use the laptop confirmation prompt." }
                            }) { Text("Approve with biometric") }
                            OutlinedButton(enabled = !answered && !busy, onClick = { reply(false, "") }) { Text("Deny") }
                            if (!permitted) Text("This action cannot use phone approval.")
                        }
                    }
                }
                Text(status)
                OutlinedButton(onClick = { finish() }) { Text("Close") }
            }
        } } }
    }
}
