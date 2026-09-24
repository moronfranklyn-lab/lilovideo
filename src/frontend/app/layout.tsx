import type { Metadata, Viewport } from "next";
import AppShell from "@/components/AppShell";
import { BRAND, BRAND_ICON } from "@/config/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: `${BRAND.name} · ${BRAND.tagline}`,
  description: BRAND.description,
  applicationName: BRAND.name,
  /**
   * 图标声明。
   *
   * `app/favicon.ico` 由 Next.js 自动接管，这里显式声明其余尺寸，
   * 让浏览器与系统按需取用，而不是把 512px 缩到 16px（那会糊掉笔画）。
   *
   * `mark`（无底板 SVG）放最前：支持 SVG 的浏览器优先用它，矢量最清晰。
   */
  icons: {
    icon: [
      { url: BRAND_ICON.mark, type: "image/svg+xml" },
      { url: "/brand/logo-32.png", sizes: "32x32", type: "image/png" },
      { url: "/brand/logo-16.png", sizes: "16x16", type: "image/png" },
      { url: "/brand/logo-48.png", sizes: "48x48", type: "image/png" },
    ],
    apple: [{ url: BRAND_ICON.appleTouch, sizes: "180x180" }],
    shortcut: [{ url: BRAND_ICON.mark }],
  },
  openGraph: {
    title: `${BRAND.name} · ${BRAND.tagline}`,
    description: BRAND.description,
    siteName: BRAND.name,
    type: "website",
  },
};

/**
 * 主题色。
 *
 * 与界面底色一致（--color-gray-25 = #0d0d12）。移动端浏览器把它用作
 * 地址栏底色，若与页面不一致会出现一条突兀的色带。
 */
export const viewport: Viewport = {
  themeColor: "#0d0d12",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className="antialiased"
      >
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
