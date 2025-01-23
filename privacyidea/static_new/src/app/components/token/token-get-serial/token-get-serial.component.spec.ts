import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { TokenGetSerial } from './token-get-serial.component';
import { HttpClient, HttpHandler } from '@angular/common/http';

describe('TokenGetSerial', () => {
  let component: TokenGetSerial;
  let fixture: ComponentFixture<TokenGetSerial>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TokenGetSerial, BrowserAnimationsModule],
      providers: [HttpClient, HttpHandler],
    }).compileComponents();

    fixture = TestBed.createComponent(TokenGetSerial);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
