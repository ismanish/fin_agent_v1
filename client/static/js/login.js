// Login functionality
document.addEventListener('DOMContentLoaded', function() {
    const loginForm = document.getElementById('login-form');
    if (!loginForm) return;

    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        const errorDiv = document.getElementById('error-message');
        const loadingDiv = document.getElementById('loading-state');
        const loginButton = document.getElementById('login-button');
        
        // Hide error message and show loading
        errorDiv.classList.add('hidden');
        loadingDiv.classList.remove('hidden');
        loginButton.disabled = true;
        
        try {
            const response = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    email: email,
                    password: password
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.authenticated) {
                // Store authentication token/flag
                localStorage.setItem('authToken', data.token);
                sessionStorage.setItem('isAuthenticated', 'true');
                
                // Show success message briefly
                loadingDiv.innerHTML = `
                    <div class="flex items-center">
                        <svg class="w-5 h-5 text-green-600 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                        <span class="text-green-700 font-medium text-sm">Login successful! Redirecting...</span>
                    </div>
                `;
                loadingDiv.className = 'p-3 bg-green-50 border border-green-200 rounded-lg';
                
                // Redirect to dashboard after a short delay
                setTimeout(() => {
                    window.location.href = '/dashboard';
                }, 1000);
            } else {
                throw new Error(data.message || 'Authentication failed');
            }
        } catch (error) {
            console.error('Login error:', error);
            
            // Hide loading and show error
            loadingDiv.classList.add('hidden');
            errorDiv.classList.remove('hidden');
            document.getElementById('error-text').textContent = error.message || 'Login failed. Please try again.';
            loginButton.disabled = false;
        }
    });
});

document.getElementById("toggle-password").addEventListener("click", function () {
  const passwordInput = document.getElementById("password");
  const eyeIcon = document.getElementById("eye-icon");
  const eyeOffIcon = document.getElementById("eye-off-icon");

  const isPassword = passwordInput.type === "password";
  passwordInput.type = isPassword ? "text" : "password";

  eyeIcon.classList.toggle("hidden", !isPassword);
  eyeOffIcon.classList.toggle("hidden", isPassword);
});
