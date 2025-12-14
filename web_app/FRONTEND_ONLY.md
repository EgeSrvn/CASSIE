# Running Frontend Only (Without Backend)

You can run and view the frontend independently without starting the backend server. This is useful for:
- UI/UX development and testing
- Design review
- Frontend-only demonstrations
- Development when backend is not needed

## Quick Start

1. **Navigate to the frontend directory:**
   ```bash
   cd frontend
   ```

2. **Install dependencies (if not already done):**
   ```bash
   npm install
   ```

3. **Start the frontend development server:**
   ```bash
   npm run dev
   ```

4. **Open your browser:**
   Navigate to `http://localhost:3000`

## What Works in Frontend-Only Mode

✅ **Fully Functional:**
- All pages are accessible and render correctly
- Navigation works
- UI components and styling
- Visual pipeline builder (can create pipelines visually)
- Form inputs and interactions
- Theme and styling

⚠️ **Limited Functionality (Backend Required):**
- User authentication (login/register won't work)
- Data upload (needs backend for presigned URLs)
- Job creation and viewing (needs backend API)
- Community workflows (needs backend to fetch)
- Pipeline saving (needs backend to store)

## Notes

- The frontend will gracefully handle backend unavailability
- API calls will fail silently or show appropriate messages
- You can still navigate all pages and see the UI
- Forms can be filled but won't submit successfully without backend

## Alternative: Mock Backend

If you want to test with mock data, you can:
1. Use browser DevTools to mock API responses
2. Set up a simple mock server using tools like `json-server`
3. Use Next.js API routes as a mock backend

## Troubleshooting

**Port already in use?**
```bash
# Use a different port
PORT=3001 npm run dev
```

**Styles not loading?**
Make sure Tailwind CSS is properly configured. The build process should handle this automatically.

**API errors in console?**
This is expected when running frontend-only. The frontend is designed to handle these gracefully.

