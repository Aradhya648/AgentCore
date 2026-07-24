import type { Metadata, Viewport } from "next";
import "./globals.css";

const TITLE = "AgentCore — 协作智能平台";
const DESCRIPTION =
  "AI 的下一步，不是更聪明的个体，而是更好的协作。AgentCore 让多个 AI Agent 像团队一样分工、协商、互审，共同完成复杂任务——你不是使用者，而是领导者。";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  keywords: [
    "AgentCore",
    "协作智能",
    "Multi-Agent",
    "多 Agent 协作",
    "AI 工作台",
    "Collaborative Intelligence",
  ],
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    locale: "zh_CN",
    siteName: "AgentCore",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: "#0c0e16",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
