//! Native file/folder selection and in-memory icon extraction. No asset files.
use crate::shell::wide;
use serde::Serialize;
use std::{
    mem::{size_of, zeroed},
    ptr::{null, null_mut},
};
use windows_sys::Win32::{
    Foundation::*,
    Graphics::Gdi::*,
    System::Com::*,
    UI::{Controls::Dialogs::*, Shell::*, WindowsAndMessaging::*},
};

#[derive(Serialize)]
pub struct Picked {
    path: String,
    name: String,
}

pub fn choose(folder: bool, owner: usize) -> Option<Picked> {
    let mut buffer = vec![0u16; 32768];
    unsafe {
        let initialized = CoInitializeEx(null(), COINIT_APARTMENTTHREADED as u32) >= 0;
        let picked = if folder {
            let mut info: BROWSEINFOW = zeroed();
            info.hwndOwner = owner as HWND;
            // Keep the title allocation alive through the modal call.
            let title = wide("Choose a project folder");
            info.lpszTitle = title.as_ptr();
            info.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
            let list = SHBrowseForFolderW(&info);
            if list.is_null() {
                false
            } else {
                let ok = SHGetPathFromIDListW(list, buffer.as_mut_ptr()) != 0;
                CoTaskMemFree(list as _);
                ok
            }
        } else {
            let filter = wide("Applications (*.exe;*.lnk)\0*.exe;*.lnk\0\0");
            let mut info: OPENFILENAMEW = zeroed();
            info.lStructSize = size_of::<OPENFILENAMEW>() as u32;
            info.hwndOwner = owner as HWND;
            info.lpstrFilter = filter.as_ptr();
            info.lpstrFile = buffer.as_mut_ptr();
            info.nMaxFile = buffer.len() as u32;
            info.Flags = OFN_FILEMUSTEXIST
                | OFN_PATHMUSTEXIST
                | OFN_NOCHANGEDIR
                | OFN_DONTADDTORECENT
                | OFN_NODEREFERENCELINKS;
            GetOpenFileNameW(&mut info) != 0
        };
        if initialized {
            CoUninitialize();
        }
        if !picked {
            return None;
        }
    }
    let end = buffer.iter().position(|c| *c == 0).unwrap_or(buffer.len());
    let path = String::from_utf16_lossy(&buffer[..end]);
    let name = std::path::Path::new(&path)
        .file_stem()?
        .to_string_lossy()
        .into();
    Some(Picked { path, name })
}

pub fn icon(path: &str) -> Result<String, String> {
    unsafe {
        let mut file: SHFILEINFOW = zeroed();
        if SHGetFileInfoW(
            wide(path).as_ptr(),
            0,
            &mut file,
            size_of::<SHFILEINFOW>() as u32,
            SHGFI_ICON | SHGFI_SMALLICON,
        ) == 0
        {
            return Err("App icon unavailable".into());
        }
        let mut info: ICONINFO = zeroed();
        if GetIconInfo(file.hIcon, &mut info) == 0 {
            DestroyIcon(file.hIcon);
            return Err("Icon bitmap unavailable".into());
        }
        let result = bitmap_png(info.hbmColor);
        DeleteObject(info.hbmColor);
        DeleteObject(info.hbmMask);
        DestroyIcon(file.hIcon);
        result
    }
}

pub fn bitmap_png(handle: HBITMAP) -> Result<String, String> {
    use base64::Engine;
    unsafe {
        let mut bitmap: BITMAP = zeroed();
        GetObjectW(
            handle,
            size_of::<BITMAP>() as i32,
            &mut bitmap as *mut _ as _,
        );
        let (width, height) = (bitmap.bmWidth, bitmap.bmHeight);
        if width <= 0 || height <= 0 || width > 256 || height > 256 {
            return Err("Unsupported icon dimensions".into());
        }
        let dc = GetDC(null_mut());
        let mut dib: BITMAPINFO = zeroed();
        dib.bmiHeader.biSize = size_of::<BITMAPINFOHEADER>() as u32;
        dib.bmiHeader.biWidth = width;
        dib.bmiHeader.biHeight = -height;
        dib.bmiHeader.biPlanes = 1;
        dib.bmiHeader.biBitCount = 32;
        dib.bmiHeader.biCompression = BI_RGB;
        let mut pixels = vec![0u8; width as usize * height as usize * 4];
        let copied = GetDIBits(
            dc,
            handle,
            0,
            height as u32,
            pixels.as_mut_ptr() as _,
            &mut dib,
            DIB_RGB_COLORS,
        );
        ReleaseDC(null_mut(), dc);
        if copied == 0 {
            return Err("Could not read icon pixels".into());
        }
        let has_alpha = pixels.chunks(4).any(|p| p[3] != 0);
        for p in pixels.chunks_mut(4) {
            p.swap(0, 2);
            if !has_alpha {
                p[3] = 255;
            }
        }
        let mut output = vec![];
        {
            let mut encoder = png::Encoder::new(&mut output, width as u32, height as u32);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder
                .write_header()
                .map_err(|e| e.to_string())?
                .write_image_data(&pixels)
                .map_err(|e| e.to_string())?;
        }
        Ok(format!(
            "data:image/png;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(output)
        ))
    }
}
