import { RenderMode, ServerRoute } from '@angular/ssr';

export const serverRoutes: ServerRoute[] = [

// --- CSR (Client-only) ---
  { path: 'login', renderMode: RenderMode.Client },
  { path: 'register', renderMode: RenderMode.Client },
  { path: 'logout', renderMode: RenderMode.Client },

  { path: 'cart', renderMode: RenderMode.Client },
  { path: 'checkout', renderMode: RenderMode.Client },
  { path: 'payment/:orderId', renderMode: RenderMode.Client },

  // support/admin section: treat everything under /support as CSR
  { path: 'support', renderMode: RenderMode.Client },
  { path: 'support/products/new', renderMode: RenderMode.Client },
  { path: 'profile', renderMode: RenderMode.Client },

  // ✅ SSG
  { path: 'products', renderMode: RenderMode.Prerender },
  { path: 'policies', renderMode: RenderMode.Prerender },

  // ✅ SSR
  { path: 'product/:id', renderMode: RenderMode.Server },
  { path: 'orders', renderMode: RenderMode.Server },
  { path: 'order/:orderId', renderMode: RenderMode.Server },

  // fallback
  { path: '**', renderMode: RenderMode.Server },
];