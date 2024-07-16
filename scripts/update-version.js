import fs from 'fs'
const configPath = "src-tauri/tauri.conf.json"
const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
console.log(config.package.version)
const signaturePath = `src-tauri/target/release/bundle/msi/TikTokMatrix_${config.package.version}_x64_en-US.msi.zip.sig`
const signature = fs.readFileSync(signaturePath, 'utf-8')
console.log(signature)
const updateJson = {
    "version": `v${config.package.version}`,
    "notes": `v${config.package.version} is released! Please update to the new version.`,
    "pub_date": new Date().toISOString(),
    "platforms": {
        "windows-x86_64": {
            "signature": signature,
            "url": `https://www.tiktokmatrix.com/TikTokMatrix_${config.package.version}_x64_en-US.msi.zip`
        }
    }
}
const updateJsonStr = JSON.stringify(updateJson, null, 2)
console.log(updateJsonStr)
fs.writeFileSync('update.json', updateJsonStr)

