package dev.friday.companion

import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import dev.friday.core.Protocol
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/** Separate from the transport key: every approval signature needs a fresh strong biometric. */
class ApprovalKey(private val context: Context) {
    private val alias = "friday-approval-p256"
    private fun vault() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    @Synchronized fun ensure() {
        if (vault().containsAlias(alias)) return
        fun generate(strongBox: Boolean) {
            val builder = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256)
                .setUserAuthenticationRequired(true).setInvalidatedByBiometricEnrollment(true)
                .setIsStrongBoxBacked(strongBox)
            if (Build.VERSION.SDK_INT >= 30) builder.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
            else { @Suppress("DEPRECATION") builder.setUserAuthenticationValidityDurationSeconds(-1) }
            KeyPairGenerator.getInstance("EC", "AndroidKeyStore").apply { initialize(builder.build()) }.generateKeyPair()
        }
        if (context.packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)) {
            try { generate(true) } catch (_: StrongBoxUnavailableException) { generate(false) }
        } else generate(false)
        check(vault().getKey(alias, null).encoded == null)
    }
    val pem: String get() { ensure(); return Protocol.pem(vault().getCertificate(alias).publicKey.encoded) }
    fun renewForEnrollment(): String {
        // Explicit setup is also recovery after Android invalidates a changed biometric enrollment.
        vault().deleteEntry(alias)
        return pem
    }
    fun approve(activity: Activity, canonical: String, summary: String, completed: (String?) -> Unit): CancellationSignal {
        require(canonical.toByteArray(Charsets.UTF_8).size <= 12000)
        ensure()
        val signature = Signature.getInstance("SHA256withECDSA").apply {
            initSign(vault().getKey(alias, null) as java.security.PrivateKey)
        }
        val cancellation = CancellationSignal()
        val builder = BiometricPrompt.Builder(activity).setTitle("Approve FRIDAY action")
            .setSubtitle(summary.take(120)).setConfirmationRequired(true)
            .setNegativeButton("Deny", activity.mainExecutor) { _, _ -> completed(null) }
        if (Build.VERSION.SDK_INT >= 30) builder.setAllowedAuthenticators(android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_STRONG)
        builder.build().authenticate(BiometricPrompt.CryptoObject(signature), cancellation, activity.mainExecutor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    completed(runCatching {
                        val authenticated = result.cryptoObject!!.signature!!
                        authenticated.update((canonical + "\naccept").toByteArray(Charsets.UTF_8))
                        Protocol.b64(authenticated.sign())
                    }.getOrNull())
                }
                override fun onAuthenticationError(code: Int, message: CharSequence) { completed(null) }
            })
        return cancellation
    }
}
