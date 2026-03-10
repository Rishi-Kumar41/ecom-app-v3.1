import { Routes } from '@angular/router';
import { canActivateAuth } from './guards/auth.guard';

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
import { AiAgentComponent } from './pages/ai-agent/ai-agent.component';

export const routes: Routes = [
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
  { path: 'agent', component: AiAgentComponent },
  { path: '**', redirectTo: '' }
];
