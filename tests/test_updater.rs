use buddy::updater::{release_package, ReleaseAsset, UpdateInfo};

#[test]
fn test_release_package_mappings() {
    let (name, ext, os) = release_package("darwin", "arm64").unwrap();
    assert_eq!(name, "buddy-macos-arm64.pkg");
    assert_eq!(ext, "pkg");
    assert_eq!(os, "darwin");

    let (name, ext, os) = release_package("linux", "x86_64").unwrap();
    assert_eq!(name, "buddy-linux-x64.tar.gz");
    assert_eq!(ext, "tgz");
    assert_eq!(os, "linux");

    let (name, ext, os) = release_package("windows", "x86_64").unwrap();
    assert_eq!(name, "buddy-windows-x64.zip");
    assert_eq!(ext, "zip");
    assert_eq!(os, "windows");
}

#[test]
fn test_update_info_version_comparisons() {
    let info = UpdateInfo {
        current_version: "0.3.4".to_string(),
        latest_version: "0.3.5".to_string(),
        release_url: "https://github.com/sarankars/buddy_cli/releases/tag/v0.3.5".to_string(),
        package: ReleaseAsset {
            name: "buddy-macos-arm64.pkg".to_string(),
            download_url: "https://...".to_string(),
            size: 1000,
            digest: None,
        },
        checksum: ReleaseAsset {
            name: "buddy-macos-arm64.pkg.sha256".to_string(),
            download_url: "https://...".to_string(),
            size: 64,
            digest: None,
        },
        archive_type: "pkg".to_string(),
    };

    assert!(info.update_available());
    assert!(!info.current_is_newer());

    let same_version_info = UpdateInfo {
        current_version: "0.3.5".to_string(),
        ..info
    };
    assert!(!same_version_info.update_available());
    assert!(!same_version_info.current_is_newer());
}
