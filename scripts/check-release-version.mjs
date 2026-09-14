// 校验 package.json / tauri.conf.json / Cargo.toml 三处版本号一致且为三段数字。
// 原为 PowerShell 脚本,macOS 运行器没有 pwsh,改写成 Node 以便 Windows 与 macOS
// 发布流程共用同一份实现。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const readJson = (relative) =>
  JSON.parse(readFileSync(join(root, relative), "utf8"));

// 取第一处 `version = "..."`,即 [package] 段的版本,与原 PowerShell 的 -First 1 一致。
const cargoMatch = readFileSync(join(root, "src-tauri/Cargo.toml"), "utf8")
  .match(/^version\s*=\s*"([^"]+)"/m);
if (!cargoMatch) {
  console.error("在 src-tauri/Cargo.toml 中找不到 version 字段");
  process.exit(1);
}

const versions = [
  ["package.json", readJson("package.json").version],
  ["tauri.conf.json", readJson("src-tauri/tauri.conf.json").version],
  ["Cargo.toml", cargoMatch[1]],
];

const malformed = versions.filter(([, value]) => !/^\d+\.\d+\.\d+$/.test(value ?? ""));
if (malformed.length > 0) {
  console.error(
    "发布版本必须是三段数字，当前值：" +
      versions.map(([name, value]) => `${name}=${value}`).join(", "),
  );
  process.exit(1);
}

if (new Set(versions.map(([, value]) => value)).size !== 1) {
  console.error(
    "package.json、tauri.conf.json 与 Cargo.toml 的版本必须一致：" +
      versions.map(([name, value]) => `${name}=${value}`).join(", "),
  );
  process.exit(1);
}

const version = versions[0][1];
console.log(`Release version verified: ${version}; MSIX version: ${version}.0`);
