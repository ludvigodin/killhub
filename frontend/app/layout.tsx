import type { Metadata } from "next";
import { DM_Sans, Syne } from "next/font/google";
import { homeDescription, homeTitle } from "@/lib/seo";
import "./globals.css";

const syne = Syne({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://killhub.pro"),
  title: {
    default: homeTitle,
    template: "%s · Killhub",
  },
  description: homeDescription,
  applicationName: "Killhub",
  openGraph: {
    // Relative to the current path, so each URL gets its own og:url.
    url: "./",
    siteName: "Killhub",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${syne.variable} ${dmSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
