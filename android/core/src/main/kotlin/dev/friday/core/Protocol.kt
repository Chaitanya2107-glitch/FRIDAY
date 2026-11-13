package dev.friday.core

import java.net.URI
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.Signature
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import kotlinx.serialization.json.*

object Protocol {
    fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
    fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }
    fun b64(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    fun decode(value: String): ByteArray = Base64.getUrlDecoder().decode(value)
    fun nonce() = b64(ByteArray(24).also { SecureRandom().nextBytes(it) })
    fun canonical(method: String, path: String, body: ByteArray, timestamp: String, nonce: String) =
        listOf(method.uppercase(java.util.Locale.ROOT), path, hex(sha256(body)), timestamp, nonce).joinToString("\n").toByteArray(Charsets.UTF_8)
    fun keyId(der: ByteArray) = hex(sha256(der)).take(32)
    fun pem(der: ByteArray) = "-----BEGIN PUBLIC KEY-----\n" + Base64.getEncoder().encodeToString(der).chunked(64).joinToString("\n") + "\n-----END PUBLIC KEY-----\n"
    fun publicDer(pem: String) = Base64.getDecoder().decode(pem.replace(Regex("-----[^-]+-----|\\s"), ""))
    fun verifyLaptop(reply: JsonObject, nonce: String, fingerprint: String, device: String) {
        val proof = reply.getValue("proof").jsonObject
        val payload = proof.getValue("payload").jsonObject
        require(payload.getValue("device_id").jsonPrimitive.content == device)
        require(payload.getValue("nonce").jsonPrimitive.content == nonce)
        require(payload.getValue("state") == reply.getValue("state"))
        val der = publicDer(proof.getValue("public_key").jsonPrimitive.content)
        require("sha256:" + hex(sha256(der)) == fingerprint) { "Laptop fingerprint mismatch" }
        val encoded = buildJsonObject {
            put("device_id", device); put("nonce", nonce); put("state", payload.getValue("state"))
        }.toString().toByteArray(Charsets.UTF_8)
        val verifier = Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(der)))
        verifier.update(encoded)
        require(verifier.verify(decode(proof.getValue("signature").jsonPrimitive.content))) { "Invalid laptop proof" }
    }
}

data class PairingGrant(val origin: String, val token: String, val fingerprint: String, val expires: Double) {
    companion object {
        fun origin(value: String): String {
            val uri = URI(value)
            require(uri.scheme == "https" && uri.host != null && uri.host.lowercase().endsWith(".ts.net")) { "Use your laptop's HTTPS Tailscale QR" }
            require(uri.userInfo == null && uri.query == null && uri.fragment == null && uri.port in listOf(-1, 443) && uri.path in listOf("", "/"))
            return "https://" + uri.host.lowercase()
        }
        fun parse(text: String, now: Double): PairingGrant {
            require(text.length <= 4096)
            val value = Json.parseToJsonElement(text).jsonObject
            require(value.getValue("signing_prefix").jsonPrimitive.content == "/remote")
            val expires = value.getValue("expires").jsonPrimitive.double
            require(expires.isFinite() && expires > now && expires <= now + 180) { "QR expired; ask the laptop for a fresh one" }
            val fingerprint = value.getValue("fingerprint").jsonPrimitive.content
            require(fingerprint.matches(Regex("sha256:[a-f0-9]{64}")))
            val token = value.getValue("token").jsonPrimitive.content
            require(token.length in 16..128)
            return PairingGrant(origin(value.getValue("url").jsonPrimitive.content), token, fingerprint, expires)
        }
    }
}
