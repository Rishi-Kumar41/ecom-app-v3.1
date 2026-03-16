// client/src/guards/role.guard.ts
import { inject } from '@angular/core';
import { CanActivateFn, Router, RouterStateSnapshot, ActivatedRouteSnapshot } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  // Allow only admins
  if (auth.isAdmin && auth.isAdmin()) {
    return true;
  }

  // Not admin → clean redirect to login, preserving intended destination
  return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
};
