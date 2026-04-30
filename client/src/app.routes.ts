import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { userGuard } from './guards/user.guard';

import { ProductsComponent } from './pages/products/products.component';
import { ProductDetailsComponent } from './pages/product-details/product-details.component';
import { CartComponent } from './pages/cart/cart.component';
import { CheckoutComponent } from './pages/checkout/checkout.component';
import { PaymentComponent } from './pages/payment/payment.component';
import { OrdersComponent } from './pages/orders/orders.component';
import { OrderDetailsComponent } from './pages/order-details/order-details.component';
import { ProfileComponent } from './pages/profile/profile.component';
import { LoginComponent } from './pages/login/login.component';
import { RegisterComponent } from './pages/register/register.component';
import { roleGuard } from './guards/role.guard';
// import { AiAgentComponent } from './pages/ai-agent/ai-agent.component';

export const routes: Routes = [

// --- Public routes ---
  {
    path: 'login',
    loadComponent: () =>
      import('./pages/login/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'register',
    loadComponent: () =>
      import('./pages/register/register.component').then(m => m.RegisterComponent),
  },

  // --- Guarded app routes ---
  {
    path: '',
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'products' },
      {
        path: 'support',
        canActivate: [roleGuard],  // must be admin
        loadComponent: () =>
          import('./pages/support/support-layout.component').then(m => m.SupportLayoutComponent),
      },
      {
        path: 'support/products/new',
        canActivate: [roleGuard],  // must be admin
        loadComponent: () =>
          import('./pages/support/add-product/add-product.component').then(m => m.AddProductComponent),
      },
      {
        path: 'logout',
        loadComponent: () => import('./pages/logout/logout.component').then(m => m.LogoutComponent),
      },
      {
        path: 'products',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/products/products.component').then(m => m.ProductsComponent),
      },
      {
        path: 'product/:id',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/product-details/product-details.component').then(m => m.ProductDetailsComponent),
      },
      { path: 'cart',
        canActivate: [userGuard],
        loadComponent: () => import('./pages/cart/cart.component').then(m => m.CartComponent)
      },
      {
        path: 'checkout',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/checkout/checkout.component').then(m => m.CheckoutComponent),
      },
      { path: 'payment/:orderId',
        canActivate: [userGuard],
        loadComponent: () => import('./pages/payment/payment.component').then(m => m.PaymentComponent)
      },
      {
        path: 'orders',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/orders/orders.component').then(m => m.OrdersComponent),
      },
      {
        path: 'order/:orderId',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/order-details/order-details.component').then(m => m.OrderDetailsComponent),
      },
      {
        path: 'profile',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/profile/profile.component').then(m => m.ProfileComponent),
      },
      {
        path: 'policies',
        canActivate: [userGuard],
        loadComponent: () =>
          import('./pages/policies/policies.component').then(m => m.PoliciesComponent),
      }
      // If you added pages like payment success/failure in UI, keep them guarded too:
      // { path: 'payment-success', loadComponent: () => import('./pages/payment/success.component').then(m => m.SuccessComponent) },
      // { path: 'payment-failed',  loadComponent: () => import('./pages/payment/failed.component').then(m => m.FailedComponent) },
    ],
  },
  // { path: 'agent', component: AiAgentComponent },
  { path: '**', redirectTo: '' }
];

/*
{ path: '', component: ProductsComponent },
  { path: 'product/:id', component: ProductDetailsComponent },
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },
  { path: 'profile', component: ProfileComponent, canActivate: [canActivateAuth] },
  { path: 'cart', component: CartComponent },
  { path: 'checkout', component: CheckoutComponent, canActivate: [canActivateAuth] },
  { path: 'payment/:orderId', component: PaymentComponent, canActivate: [canActivateAuth] },
  { path: 'order/:orderId', component: OrderDetailsComponent, canActivate: [canActivateAuth] },
  { path: 'orders', component: OrdersComponent, canActivate: [canActivateAuth] },
*/