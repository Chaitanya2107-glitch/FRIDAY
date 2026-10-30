fn main() {
    // Original app icon generated at build time. The on-screen character is SVG.
    let icon = std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("island.ico");
    let mut bytes = vec![0, 0, 1, 0, 1, 0, 32, 32, 0, 0, 1, 0, 32, 0];
    bytes.extend_from_slice(&4264u32.to_le_bytes());
    bytes.extend_from_slice(&22u32.to_le_bytes());
    for value in [40u32, 32, 64, 0x00200001, 0, 4096, 0, 0, 0, 0] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    for y in (0..32i32).rev() {
        for x in 0..32i32 {
            let visible = (x - 16).pow(2) + (y - 16).pow(2) < 195;
            let eye = ((x - 12).abs() < 2 || (x - 20).abs() < 2) && (14..19).contains(&y);
            bytes.extend_from_slice(if eye {
                &[19, 24, 30, 255]
            } else if visible {
                &[71, 179, 255, 255]
            } else {
                &[0, 0, 0, 0]
            });
        }
    }
    bytes.extend_from_slice(&[0u8; 128]);
    std::fs::write(&icon, bytes).unwrap();
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .windows_attributes(tauri_build::WindowsAttributes::new().window_icon_path(icon)),
    )
    .expect("Tauri build configuration failed");
}
