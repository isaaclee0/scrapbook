"""
Email service for sending authentication emails via Brevo API
"""

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
import os

# Configure Brevo API
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = os.getenv('BREVO_API_KEY')

api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))


def send_otp_email(email: str, otp: str) -> bool:
    """
    Send an OTP authentication email via Brevo
    
    Args:
        email: Recipient email address
        otp: 6-digit OTP code
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Create email content
        subject = "Your Scrapbook Login Code"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .container {{
                    background: #f8f9fa;
                    padding: 30px;
                    border-radius: 10px;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .header h1 {{
                    color: #2c3e50;
                    margin: 0;
                    font-size: 28px;
                }}
                .content {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .otp-code {{
                    text-align: center;
                    font-size: 48px;
                    font-weight: 700;
                    letter-spacing: 8px;
                    color: #2980b9;
                    background: #f0f8ff;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 30px 0;
                    font-family: 'Courier New', monospace;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    font-size: 12px;
                    color: #666;
                }}
                .expiry {{
                    background: #fff3cd;
                    padding: 12px;
                    border-radius: 6px;
                    border-left: 4px solid #ffc107;
                    margin: 15px 0;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 scrapbook.io</h1>
                </div>
                <div class="content">
                    <h2>Your Login Code</h2>
                    <p>Hi there! 👋</p>
                    <p>Use this code to log in to your Scrapbook account:</p>
                    
                    <div class="otp-code">{otp}</div>
                    
                    <div class="expiry">
                        ⏰ This code expires in <strong>10 minutes</strong> for your security.
                    </div>
                    
                    <p style="font-size: 14px; color: #666; margin-top: 20px;">
                        If you didn't request this login code, you can safely ignore this email.
                    </p>
                </div>
                <div class="footer">
                    <p>Sent by Scrapbook.io - Your Personal Scrapbook</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Login to Scrapbook
        
        Your login code is: {otp}
        
        This code expires in 10 minutes for your security.
        
        If you didn't request this login code, you can safely ignore this email.
        """
        
        # Create email object
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email}],
            sender={"name": "Scrapbook.io", "email": "noreply@scrapbook.io"},
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
        
        # Send email
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"✅ OTP email sent to {email}")
        print(f"Message ID: {api_response.message_id}")
        return True
        
    except ApiException as e:
        print(f"❌ Error sending email via Brevo: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error sending email: {e}")
        return False


# Keep the old function name for backward compatibility (deprecated)
def send_magic_link_email(email: str, magic_link: str) -> bool:
    """
    Deprecated: This function is kept for backward compatibility.
    Use send_otp_email instead.
    """
    return send_otp_email(email, "000000")  # Placeholder, should not be used


def send_welcome_email(email: str) -> bool:
    """
    Send a welcome email to new users
    
    Args:
        email: Recipient email address
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        subject = "Welcome to Scrapbook! 🎉"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .container {{
                    background: #f8f9fa;
                    padding: 30px;
                    border-radius: 10px;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .header h1 {{
                    color: #2c3e50;
                    margin: 0;
                    font-size: 32px;
                }}
                .content {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .feature {{
                    margin: 15px 0;
                    padding-left: 10px;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 20px;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎉 Welcome to Scrapbook!</h1>
                </div>
                <div class="content">
                    <p>Hi there! 👋</p>
                    <p>We're excited to have you join Scrapbook! Your account has been created and you're all set to start organizing your ideas, images, and inspiration.</p>
                    
                    <h3>What you can do with Scrapbook:</h3>
                    <div class="feature">📌 Create boards to organize your content</div>
                    <div class="feature">🖼️ Save images, websites, and ideas</div>
                    <div class="feature">🎨 Organize with sections</div>
                    <div class="feature">🔍 Search and discover your saved content</div>
                    
                    <p style="margin-top: 30px;">
                        Ready to get started? Log in anytime using your email address - no password needed!
                    </p>
                </div>
                <div class="footer">
                    <p>Happy scrapbooking! 🎨<br>The Scrapbook Team</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Welcome to Scrapbook!
        
        We're excited to have you join Scrapbook! Your account has been created and you're all set to start organizing your ideas, images, and inspiration.
        
        What you can do with Scrapbook:
        - Create boards to organize your content
        - Save images, websites, and ideas
        - Organize with sections
        - Search and discover your saved content
        
        Ready to get started? Log in anytime using your email address - no password needed!
        
        Happy scrapbooking!
        The Scrapbook Team
        """
        
        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": email}],
            sender={"name": "Scrapbook.io", "email": "noreply@scrapbook.io"},
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )
        
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"✅ Welcome email sent to {email}")
        return True
        
    except ApiException as e:
        print(f"❌ Error sending welcome email: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error sending welcome email: {e}")
        return False
