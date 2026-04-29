export const PASSWORD_REQUIREMENTS = [
  'At least 8 characters',
  'One uppercase letter',
  'One lowercase letter',
  'One number',
  'One symbol',
]

export const validatePasswordComplexity = (password: string): string[] => {
  const failures: string[] = []

  if (password.length < 8) failures.push(PASSWORD_REQUIREMENTS[0])
  if (!/[A-Z]/.test(password)) failures.push(PASSWORD_REQUIREMENTS[1])
  if (!/[a-z]/.test(password)) failures.push(PASSWORD_REQUIREMENTS[2])
  if (!/[0-9]/.test(password)) failures.push(PASSWORD_REQUIREMENTS[3])
  if (!/[^A-Za-z0-9]/.test(password)) failures.push(PASSWORD_REQUIREMENTS[4])

  return failures
}

export const getPasswordRequirementText = () => PASSWORD_REQUIREMENTS.join(', ')

