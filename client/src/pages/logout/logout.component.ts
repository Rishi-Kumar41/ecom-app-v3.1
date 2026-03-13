// client/src/pages/logout/logout.component.ts
import { Component, OnInit } from '@angular/core';
import { AuthService } from '../../services/auth.service';

@Component({
  standalone: true,
  selector: 'app-logout',
  template: ''
})
export class LogoutComponent implements OnInit {
  constructor(private auth: AuthService) {}
  ngOnInit() {
    this.auth.logout('/login');     // <-- always redirect to /login after clearing
  }
}