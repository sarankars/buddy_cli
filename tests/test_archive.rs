use std::fs::{self, File};
use std::io::Write;
use tempfile::tempdir;

use buddy::archive::extract_archive;

#[test]
fn test_safe_zip_extraction() {
    let dir = tempdir().unwrap();
    let zip_path = dir.path().join("bundle.zip");
    let dest = dir.path().join("out");

    {
        let file = File::create(&zip_path).unwrap();
        let mut zip = zip::ZipWriter::new(file);
        let options = zip::write::SimpleFileOptions::default();
        zip.start_file("nested/file.txt", options).unwrap();
        zip.write_all(b"safe archive content").unwrap();
        zip.finish().unwrap();
    }

    extract_archive(&zip_path, &dest, "zip").unwrap();
    let content = fs::read_to_string(dest.join("nested/file.txt")).unwrap();
    assert_eq!(content, "safe archive content");
}

#[test]
fn test_safe_tgz_extraction() {
    let dir = tempdir().unwrap();
    let tar_path = dir.path().join("bundle.tar.gz");
    let dest = dir.path().join("out");

    {
        let file = File::create(&tar_path).unwrap();
        let enc = flate2::write::GzEncoder::new(file, flate2::Compression::default());
        let mut tar = tar::Builder::new(enc);

        let data = b"tar content";
        let mut header = tar::Header::new_gnu();
        header.set_path("hello_tar.txt").unwrap();
        header.set_size(data.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        tar.append(&header, &data[..]).unwrap();
        tar.finish().unwrap();
    }

    extract_archive(&tar_path, &dest, "tgz").unwrap();
    let content = fs::read_to_string(dest.join("hello_tar.txt")).unwrap();
    assert_eq!(content, "tar content");
}
