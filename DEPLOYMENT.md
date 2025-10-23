# FinAgent Deployment Guide

## Deploy to Railway

### Prerequisites
- GitHub account with the repository: https://github.com/ismanish/fin_agent_v1
- Railway account (sign up at https://railway.app)

### Environment Variables Required
Before deploying, you'll need to set these environment variables in Railway:

```
AZURE_OPENAI_API_KEY=your_azure_openai_key
AZURE_OPENAI_ENDPOINT=your_azure_endpoint
AZURE_OPENAI_DEPLOYMENT_NAME=your_deployment_name
AZURE_OPENAI_API_VERSION=2024-02-15-preview
SEC_API_KEY=your_sec_api_key (optional)
AZURE_STORAGE_CONNECTION_STRING=your_storage_string (optional)
```

### Deployment Steps

1. **Go to Railway**: Visit https://railway.app
2. **Sign in with GitHub**: Click "Login" and authenticate with GitHub
3. **Create New Project**: Click "New Project"
4. **Deploy from GitHub repo**: Select "Deploy from GitHub repo"
5. **Select Repository**: Choose `ismanish/fin_agent_v1`
6. **Configure Environment Variables**:
   - Click on your deployed service
   - Go to "Variables" tab
   - Add all required environment variables listed above
7. **Deploy**: Railway will automatically detect Python and deploy
8. **Get Public URL**: 
   - Go to "Settings" tab
   - Click "Generate Domain" to get a public URL
   - Your app will be available at: `https://your-app.up.railway.app`

### Post-Deployment

- Access your app at the generated Railway URL
- Login with: `admin@fin.com` / `admin123`
- Monitor logs in Railway dashboard under "Deployments" tab

### Troubleshooting

If deployment fails:
1. Check the build logs in Railway dashboard
2. Verify all environment variables are set correctly
3. Ensure `requirements.txt` has all dependencies
4. Check that Python version matches (3.11)

### Local Development

To run locally:
```bash
python app.py
```
Access at: http://localhost:9259
