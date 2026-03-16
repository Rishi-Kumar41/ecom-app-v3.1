// client/src/guards/user.guard.ts
import { inject } from '@angular/core';
import { CanActivateFn, Router, RouterStateSnapshot, ActivatedRouteSnapshot } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const userGuard: CanActivateFn = (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.isLoggedIn()) {
    return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  }

  // Only users (customers) are allowed past this guard
  if (auth.userRole && auth.userRole() === 'user') {
    return true;
  }

  // If it's an admin, send to Support instead of shopping routes
  return router.createUrlTree(['/support']);
};