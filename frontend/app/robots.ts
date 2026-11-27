import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/features", "/hubs"],
      disallow: ["/api/", "/health", "/mcp"],
    },
    sitemap: "https://killhub.pro/sitemap.xml",
  };
}
