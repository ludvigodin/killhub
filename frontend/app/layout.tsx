import type { Metadata } from "next";
import { DM_Sans, Syne } from "next/font/google";
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
    default: "Killhub",
    template: "%s · Killhub",
  },
  description:
    "Drop public git URLs into the Killhub feed. Verified sandboxes and receipts that outlive the VM.",
  applicationName: "Killhub",
  openGraph: {
    title: "Killhub",
    description:
      "Drop public git URLs into the Killhub feed. Verified sandboxes and receipts that outlive the VM.",
    url: "https://killhub.pro",
    siteName: "Killhub",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Killhub",
    description:
      "Drop public git URLs into the Killhub feed. Verified sandboxes and receipts that outlive the VM.",
  },
  alternates: {
    canonical: "/",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${syne.variable} ${dmSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
