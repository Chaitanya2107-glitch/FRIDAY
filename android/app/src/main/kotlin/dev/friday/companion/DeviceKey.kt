package dev.friday.companion

import android.content.Context
import android.content.pm.PackageManager
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import dev.friday.core.*
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

class DeviceKey(private val context: Context) : RequestKey {
    private val alias = "friday-companion-p256"
    private fun vault() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    @Synchronized fun ensure() {
        if (vault().containsAlias(alias)) return
        fun generate(strong: Boolean) {
            val spec = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256).setIsStrongBoxBacked(strong).build()
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply { initialize(spec) }.generateKeyPair()
        }
        if (context.packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)) {
            try { generate(true) } catch (_: StrongBoxUnavailableException) { generate(false) }
        } else generate(false)
        check(vault().getKey(alias, null).encoded == null) { "Private key must never be exportable" }
    }
    val der: ByteArray get() { ensure(); return vault().getCertificate(alias).publicKey.encoded }
    val id: String get() = Protocol.keyId(der)
    val pem: String get() = Protocol.pem(der)
    override fun sign(bytes: ByteArray): ByteArray {
        ensure()
        return Signature.getInstance("SHA256withECDSA").run {
            initSign(vault().getKey(alias, null) as java.security.PrivateKey); update(bytes); sign()
        }
    }
}
