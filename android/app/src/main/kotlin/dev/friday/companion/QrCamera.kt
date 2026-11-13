package dev.friday.companion

import android.content.Context
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.*
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.common.MlKit
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors

@androidx.annotation.OptIn(markerClass = [ExperimentalGetImage::class])
@Composable fun QrCamera(onCode: (String) -> Unit, onError: () -> Unit) {
    val owner = LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    var camera by remember { mutableStateOf<ProcessCameraProvider?>(null) }
    val scanner = remember { BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()) }
    DisposableEffect(Unit) { onDispose { camera?.unbindAll(); scanner.close(); executor.shutdown() } }
    AndroidView(factory = { context ->
        PreviewView(context).also { view ->
            val provider = ProcessCameraProvider.getInstance(context)
            provider.addListener({
                try {
                    camera = provider.get()
                    val preview = Preview.Builder().build().also { it.surfaceProvider = view.surfaceProvider }
                    val analyzer = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                    analyzer.setAnalyzer(executor) { frame ->
                        val media = frame.image
                        if (media == null) frame.close() else scanner.process(InputImage.fromMediaImage(media, frame.imageInfo.rotationDegrees))
                            .addOnSuccessListener { codes -> codes.firstOrNull()?.rawValue?.let { onCode(it) } }
                            .addOnCompleteListener { frame.close() }
                    }
                    camera?.unbindAll(); camera?.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analyzer)
                } catch (_: Exception) { onError() }
            }, ContextCompat.getMainExecutor(context))
        }
    })
}
