import "zone.js/node";

import express from "express";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { APP_BASE_HREF } from "@angular/common";
import { CommonEngine } from "@angular/ssr/node";
import bootstrap from "./main.server";

export function app(): express.Express {
  const server = express();

  const distFolder = join(process.cwd(), "dist/ecom-client/browser");

  // Browser index (CSR shell)
  const indexHtml = existsSync(join(distFolder, "index.original.html"))
    ? join(distFolder, "index.original.html")
    : join(distFolder, "index.html");

  // SSR engine (legacy builders compatible)
  const commonEngine = new CommonEngine({
    // Hostnames only (no http://, no ports)
    allowedHosts: ["localhost", "127.0.0.1", "::1"],
  });

  server.set("view engine", "html");
  server.set("views", distFolder);

  // Serve static assets
  server.get("*.*", express.static(distFolder, { maxAge: "1y" }));

  // ---- Route classification helpers ----

  const normalizePath = (p: string) => {
    const noQuery = p.split("?")[0];
    // remove trailing slash except root
    return noQuery !== "/" ? noQuery.replace(/\/+$/, "") : "/";
  };

  const isCsrOnly = (rawPath: string) => {
    const path = normalizePath(rawPath);

    // exact CSR routes
    if (
      [
        "/login",
        "/register",
        "/logout",
        "/cart",
        "/checkout",
        "/profile",
      ].includes(path)
    ) {
      return true;
    }

    // prefix CSR routes
    if (path.startsWith("/payment/")) return true;
    if (path.startsWith("/support")) return true;

    return false;
  };

  const isSsgStatic = (rawPath: string) => {
    const path = normalizePath(rawPath);
    return path === "/products" || path === "/policies";
  };

  const isSsrRoute = (path: string) => {
    return (
      path.startsWith("/product/") ||
      path === "/orders" ||
      path.startsWith("/order/")
    );
  };

  const tryServePrerenderedFile = (rawPath: string) => {
    const path = normalizePath(rawPath);
    const clean = path.replace(/^\/+/, "");
    const filePath = join(distFolder, clean, "index.html");
    return existsSync(filePath) ? readFileSync(filePath, "utf8") : null;
  };

  // ---- Main handler ----
  server.get("*", (req, res, next) => {
    const { protocol, originalUrl, baseUrl, headers } = req;

    // Remove query string for route classification
    const pathOnly = originalUrl.split("?")[0];

    // 1) SSG: serve prerendered static HTML if available
    if (isSsgStatic(pathOnly)) {
      const html = tryServePrerenderedFile(pathOnly);
      if (html) {
        res.status(200).send(html);
        return;
      }
      // If missing, fall back to SSR render (safe fallback)
    }

    // 2) CSR-only: return browser index.html (no SSR markers)
    if (isCsrOnly(pathOnly)) {
      res.status(200).send(readFileSync(indexHtml, "utf8"));
      return;
    }

    // 3) SSR routes (and fallback): render via CommonEngine
    if (isSsrRoute(pathOnly) || true) {
      commonEngine
        .render({
          bootstrap,
          documentFilePath: indexHtml,
          url: `${protocol}://${headers.host}${originalUrl}`,
          publicPath: distFolder,
          providers: [{ provide: APP_BASE_HREF, useValue: baseUrl }],
        })
        .then((html) => res.send(html))
        .catch((err) => next(err));
    }
  });

  return server;
}

function run(): void {
  const port = process.env["PORT"] || 4000;
  const server = app();

  server.listen(port, () => {
    console.log(`Node Express server listening on http://localhost:${port}`);
  });
}

declare const __non_webpack_require__: NodeRequire;
const mainModule = __non_webpack_require__.main;
const moduleFilename = (mainModule && mainModule.filename) || "";
if (moduleFilename === __filename || moduleFilename.includes("iisnode")) {
  run();
}

export default bootstrap;
