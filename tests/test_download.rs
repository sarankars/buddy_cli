use std::fs;
use tempfile::tempdir;

use buddy::download::sha256_file;

#[test]
fn test_sha256_calculation() {
    let dir = tempdir().unwrap();
    let file = dir.path().join("sample.txt");
    fs::write(&file, b"test content").unwrap();

    let digest = sha256_file(&file).unwrap();
    assert_eq!(
        digest,
        "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"
    );
}
