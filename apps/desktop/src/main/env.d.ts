/**
 * 主进程资源导入声明：electron-vite 的 `?asset` 后缀把文件拷入产物并解析为运行时
 * 绝对路径（字符串）。renderer 侧的 `vite/client` 只声明了 `*.png` 等裸导入、不含
 * `?asset` 查询，故在此补一条，供 `import icon from "../../resources/icon.png?asset"`
 * 在主进程编译里得到正确类型。
 */
declare module "*?asset" {
  const assetPath: string;
  export default assetPath;
}
