import type { Metadata } from "next";

export const homeTitle = "Sandbox a public repo, then destroy the VM";

export const homeDescription =
  "Paste a public git URL. Killhub plans the run, executes it in a disposable Vultr Microsandbox, returns evidence, and destroys the VM. The receipt stays.";

export const featuresTitle = "How Killhub runs a repo";

export const featuresDescription =
  "Plan, sandboxed execution, verifiable output, destroy. One public git URL becomes a disposable microVM and a receipt that outlives it.";

export const hubsTitle = "Public runs";

export const hubsDescription =
  "Every public repository Killhub has planned, sandboxed, and verified. Latest run first.";

export const noindexRobots: Metadata["robots"] = {
  index: false,
  follow: false,
};

const featureList = [
  "Plans an executable profile from a public git URL",
  "Runs it in one disposable Microsandbox",
  "Returns readiness evidence and cited advisories",
  "Destroys the VM and keeps the receipt",
];

export const homeJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      name: "Killhub",
      url: "https://killhub.pro/",
      description: homeDescription,
    },
    {
      "@type": "SoftwareApplication",
      name: "Killhub",
      applicationCategory: "DeveloperApplication",
      operatingSystem: "Web",
      url: "https://killhub.pro/",
      description: homeDescription,
      featureList,
    },
  ],
};
