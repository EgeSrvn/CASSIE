import { useLocation } from 'react-router-dom'
import { configCatAuth } from '../../cats/config_cat_auth'
import { configCatCommunity } from '../../cats/config_cat_community'
import { configCatHome } from '../../cats/config_cat_home'
import { configCatJobs } from '../../cats/config_cat_jobs'
import { configCatPipelines } from '../../cats/config_cat_pipelines'
import { configCatProfile } from '../../cats/config_cat_profile'
import type { CatCornerConfig } from '../../cats/types'
import CatCornerCard from './CatCornerCard'

function getCatConfig(pathname: string): CatCornerConfig | null {
  if (pathname === '/jobs/create' || pathname.startsWith('/pipelines/builder')) {
    return null
  }

  if (pathname === '/') {
    return configCatHome
  }

  if (
    pathname === '/login' ||
    pathname === '/register' ||
    pathname === '/verify-email' ||
    pathname === '/forgot-password'
  ) {
    return configCatAuth
  }

  if (pathname === '/jobs' || pathname.startsWith('/jobs/')) {
    return configCatJobs
  }

  if (pathname === '/pipelines' || pathname === '/pipelines/templates') {
    return configCatPipelines
  }

  if (
    pathname === '/community' ||
    pathname === '/forum' ||
    pathname === '/forum/new' ||
    pathname.startsWith('/forum/')
  ) {
    return configCatCommunity
  }

  if (
    pathname === '/profile' ||
    pathname.startsWith('/profile/') ||
    pathname.startsWith('/pages/') ||
    pathname === '/contact' ||
    pathname === '/about' ||
    pathname === '/help' ||
    pathname === '/tutorial'
  ) {
    return configCatProfile
  }

  return configCatAuth
}

export default function SiteCatWidget() {
  const { pathname } = useLocation()
  const config = getCatConfig(pathname)

  if (!config) {
    return null
  }

  return <CatCornerCard config={config} />
}
