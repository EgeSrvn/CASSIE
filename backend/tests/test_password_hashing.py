from backend.api.models.user_model import hash_password, verify_password


def test_long_password_hash_and_verify():
    # create a password longer than bcrypt's 72-byte limit
    long_password = "p" * 100
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed) is True
