/** 剪贴板内容：一个待复制/剪切的源内路径 + 操作类型。 */
export type ClipboardEntry = { op: "copy" | "cut"; path: string };

export interface FileTreeHandle {
  /** 由外层（如多根工作区的根节点右键菜单）触发的「在源根处内联新建」。 */
  startCreate: (kind: "file" | "dir") => void;
  /** 刷新根 + 所有已展开目录。 */
  refresh: () => void;
  /** 打开 OS 文件选择器，上传到源根（仅可传输的源）。 */
  triggerUpload: () => void;
  /** 收起全部展开目录（外置工具栏的「全部折叠」用）。 */
  collapseAll: () => void;
}

/** 树内部「工具栏相关」的活动状态，供外置工具栏（如侧栏面板头）响应式渲染。 */
export interface FileTreeChromeState {
  /** 正在上传（上传按钮转圈/禁用）。 */
  uploading: boolean;
  /** 有已展开目录（决定是否显示「全部折叠」）。 */
  hasExpanded: boolean;
  /** 根正在加载（刷新按钮转圈）。 */
  loading: boolean;
}
