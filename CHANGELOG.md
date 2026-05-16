## [1.0.0] - 2026-01-07

### Added
- **Export conversations as JSON** - Download your entire conversation history in JSON format, matching the existing markdown and PDF export options
- **Delete conversations** - Remove conversations you no longer need from your account
- **Search and filter conversations** - Quickly find conversations by title, filter by date range, and sort by your preferred order
- **Model performance analytics** - View which AI models perform best based on historical ranking data
- **Mobile support** - The application now works properly on mobile devices and tablets with responsive design
- **Improved notifications** - Replaced disruptive popup alerts with smooth, non-blocking toast notifications

### Fixed
- **Critical security: Added authentication** - Fixed vulnerability that allowed any user with network access to create conversations, send messages, and access any conversation without permission
- **Critical security: Removed hardcoded credentials** - Fixed default API key that could be exploited if environment configuration is misconfigured
- **Critical security: Added rate limiting** - Prevented potential abuse by adding request limits to message and API endpoints
- **Reduced sensitive error exposure** - Fixed information leakage in error messages that could reveal internal system details
- **Added message validation** - Messages are now validated for length and content to prevent system issues
- **Fixed message input form** - Users can now send follow-up messages in conversations (previously only the first message was possible)
- **Added keyboard navigation** - Improved accessibility with proper keyboard navigation support for tab components
- **Added focus indicators** - Interactive elements now display visible focus states for keyboard users