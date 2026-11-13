package dev.friday.companion

import android.Manifest
import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.google.mlkit.common.MlKit
import dev.friday.core.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

@Composable fun PairingUi(context: Context, onPaired: () -> Unit) {
    val repo = context.repository
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }; var name by remember { mutableStateOf("My Android phone") }
    var pin by remember { mutableStateOf("") }; var message by remember { mutableStateOf("") }
    var camera by remember { mutableStateOf(false) }; var cameraExplanation by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    suspend fun checkPending() {
        busy = true
        try {
            val verified = withContext(Dispatchers.IO) {
                val reply = repo.client().json("GET", "pair/status")
                Protocol.verifyLaptop(reply.body, reply.nonce, repo.settings.fingerprint, repo.key.id)
                reply.body.getValue("state").jsonPrimitive.content == "paired"
            }
            if (verified) { repo.settings.paired = true; onPaired() }
            else message = "Still waiting for laptop approval. You can check again after approving."
        } catch (_: Exception) { message = "No verified pairing yet. If the QR expired or was rejected, use a fresh one." }
        finally { busy = false }
    }
    LaunchedEffect(Unit) { if (repo.settings.origin.isNotEmpty() && repo.settings.fingerprint.isNotEmpty()) checkPending() }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) { MlKit.initialize(context.applicationContext); camera = true } else message = "Camera denied. Paste the pairing JSON instead."
    }
    Text("Pair with your laptop", style = MaterialTheme.typography.headlineSmall)
    Text("Enable remote on the laptop, say ‘pair my phone’, and scan or paste its one-time QR. The laptop will explicitly approve phone_data; every signal starts OFF.")
    Button(onClick = { cameraExplanation = true }, enabled = !busy) { Text("Scan laptop QR") }
    if (camera) {
        Box(Modifier.fillMaxWidth().height(240.dp)) { QrCamera(onCode = { code = it; camera = false }, onError = { camera = false; message = "Camera unavailable. Paste the QR JSON." }) }
        TextButton(onClick = { camera = false }) { Text("Close camera") }
    }
    OutlinedTextField(code, { code = it }, label = { Text("Paste complete pairing JSON") }, enabled = !busy, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(name, { name = it.take(60) }, label = { Text("Phone name") }, enabled = !busy, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(pin, { pin = it.filter(Char::isDigit).take(6) }, label = { Text("Set 6-digit approval PIN") }, visualTransformation = PasswordVisualTransformation(), enabled = !busy)
    Button(enabled = !busy && pin.matches(Regex("[0-9]{6}")), onClick = {
        busy = true; camera = false
        scope.launch {
            val approvalPin = pin; pin = ""
            try {
                withContext(Dispatchers.IO) {
                    val grant = PairingGrant.parse(code, System.currentTimeMillis() / 1000.0)
                    repo.key.ensure(); repo.settings.origin = grant.origin; repo.settings.fingerprint = grant.fingerprint
                    val client = repo.client()
                    val response = client.json("POST", "pair", buildJsonObject {
                        put("token", grant.token); put("name", name.trim()); put("public_key", repo.key.pem); put("pin", approvalPin)
                        put("scopes", JsonArray(listOf(JsonPrimitive("phone_data"))))
                    })
                    Protocol.verifyLaptop(response.body, response.nonce, grant.fingerprint, repo.key.id)
                    withContext(Dispatchers.Main) { code = ""; message = "Approve this phone on your laptop. Waiting for its signed confirmation…" }
                    var accepted = false
                    repeat(28) {
                        if (!accepted) {
                            delay(4000)
                            val status = client.json("GET", "pair/status")
                            Protocol.verifyLaptop(status.body, status.nonce, grant.fingerprint, repo.key.id)
                            if (status.body.getValue("state").jsonPrimitive.content == "paired") accepted = true
                        }
                    }
                    require(accepted) { "Pairing expired. Ask for another QR." }
                    repo.settings.paired = true
                }
                onPaired()
            } catch (_: Exception) { message = "Pairing was not verified. Check laptop consent, Tailscale and the phone clock, then use a fresh QR." }
            finally { busy = false }
        }
    }) { Text(if (busy) "Waiting for laptop…" else "Pair and verify laptop") }
    Text(message)
    if (repo.settings.origin.isNotEmpty() && repo.settings.fingerprint.isNotEmpty()) TextButton(enabled = !busy, onClick = { scope.launch { checkPending() } }) { Text("Check pending laptop approval") }
    if (cameraExplanation) AlertDialog(onDismissRequest = { cameraExplanation = false }, title = { Text("Camera for one QR") },
        text = { Text("Camera is used only while this scanner is open. The bundled QR model works locally; non-tailnet TLS is blocked app-wide, including SDK metrics. No camera images are stored or sent.") },
        confirmButton = { TextButton(onClick = { cameraExplanation = false; permission.launch(Manifest.permission.CAMERA) }) { Text("Continue to camera permission") } },
        dismissButton = { TextButton(onClick = { cameraExplanation = false }) { Text("Use paste instead") } })
}
