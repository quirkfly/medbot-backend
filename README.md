
# Medbot Backend

The backend service for Medbot, a medical chatbot designed to assist users in understanding their health conditions and providing relevant information.

## Features

- **Symptom Analysis**: Processes user inputs to determine possible health conditions.
- **Medical Information Retrieval**: Access to a wide range of medical data and suggestions.
- **Secure Communication**: Ensures user privacy and data protection.

## Technologies Used

- **Python**: Programming language for backend development.
- **Flask**: Web framework for building the application.
- **OAuth2**: Authentication protocol for secure access.

## Installation

To set up the project locally:

1. Clone the repository:

   ```bash
   git clone https://github.com/quirkfly/medbot-backend.git
   cd medbot-backend
   ```

2. Create a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set up the database:

   ```bash
   flask db upgrade
   ```

5. Start the development server:

   ```bash
   flask run
   ```

   The application will be available at `http://localhost:5000`.

## Usage

Once the application is running, you can interact with the Medbot backend through the available API endpoints. Refer to the API documentation for detailed information on usage.

## Contributing

Contributions are welcome! Please fork the repository, make your changes, and submit a pull request. Ensure that your code adheres to the project's coding standards and includes appropriate tests.

## License

This project is licensed under the MIT License.
