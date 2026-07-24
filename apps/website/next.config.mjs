/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pure static marketing site → export to plain HTML/CSS/JS so it can be
  // hosted on any static host (Vercel, 阿里云 OSS, Nginx) without a Node server.
  output: "export",
  // 产出 /download/index.html，Cloudflare Pages 可直接响应 /download/ 与 /download。
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
