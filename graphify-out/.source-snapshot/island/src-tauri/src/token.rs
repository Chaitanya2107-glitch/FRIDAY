//! A 32-byte OS-generated bridge secret, encoded as 64 hexadecimal characters.
pub fn new_token() -> String {
    let mut bytes = [0u8; 32];
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::Security::Cryptography::{
            BCryptGenRandom, BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        };
        assert!(
            BCryptGenRandom(
                std::ptr::null_mut(),
                bytes.as_mut_ptr(),
                32,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG
            ) >= 0,
            "Windows random generator unavailable"
        );
    }
    #[cfg(not(windows))]
    {
        use std::io::Read;
        std::fs::File::open("/dev/urandom")
            .and_then(|mut file| file.read_exact(&mut bytes))
            .expect("OS random generator unavailable");
    }
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(test)]
mod tests {
    use crate::config::load;
    use std::fs;
    use uuid::Uuid;

    #[test]
    fn secrets_are_unique_32_byte_hex_values() {
        let token = super::new_token();
        assert_eq!(token.len(), 64);
        assert!(token.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_ne!(token, super::new_token());
    }

    #[test]
    fn missing_token_is_materialized_once() {
        let root = std::env::temp_dir().join(format!("friday-island-test-{}", Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("config.json");
        fs::write(&path, r##"{"appearance":{"glow":"#FF9900"}}"##).unwrap();
        let first = load(&path).unwrap();
        assert_eq!(
            first.connection.token,
            load(&path).unwrap().connection.token
        );
        assert_eq!(first.appearance.glow, "#FF9900");
        assert!(fs::read_to_string(&path)
            .unwrap()
            .contains(&first.connection.token));
        fs::remove_dir_all(root).unwrap();
    }
}
