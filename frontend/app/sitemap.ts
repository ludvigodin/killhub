import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: "https://killhub.pro/" },
    { url: "https://killhub.pro/features" },
    { url: "https://killhub.pro/hubs" },
  ];
}
