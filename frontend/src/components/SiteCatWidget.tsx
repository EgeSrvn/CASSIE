import { useLocation } from 'react-router-dom'
import { configCatAuth } from '../../cats/config_cat_auth'
import { configCatCommunity } from '../../cats/config_cat_community'
import { configCatForum } from '../../cats/config_cat_forum'
import { configCatForumComposer } from '../../cats/config_cat_forum_composer'
import { configCatHome } from '../../cats/config_cat_home'
import { configCatJobs } from '../../cats/config_cat_jobs'
import { configCatPipelines } from '../../cats/config_cat_pipelines'
import { configCatProfile } from '../../cats/config_cat_profile'
import { configCatStorage } from '../../cats/config_cat_storage'  
import { configCatStoragePlan } from '../../cats/config_cat_storage_plan'
import { configCatBalance } from '../../cats/config_cat_balance'
import type { CatCornerConfig } from '../../cats/types'
import CatCornerCard from './CatCornerCard'

function getCatConfig(pathname: string): CatCornerConfig | null {
  if (pathname === '/jobs/create' || pathname.startsWith('/pipelines/builder')) {
    return null
  }

  if (
    pathname === '/about' ||
    pathname === '/contact' ||
    pathname === '/faq' ||
    pathname === '/help' ||
    pathname === '/tutorial' ||
    pathname.startsWith('/pages/')
  ) {
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

  if (pathname === '/community') {
    return configCatCommunity
  }

  if (pathname === '/forum/new') {
    return configCatForumComposer
  }

  if (pathname === '/forum' || pathname.startsWith('/forum/')) {
    return configCatForum
  }

  if (
    pathname === '/profile' ||
    pathname.startsWith('/profile/')
  ) {
    return configCatProfile
  }

  if (pathname === '/storage/upgrade') {
    return configCatStoragePlan
  }

  if (pathname === '/storage' || pathname.startsWith('/storage/')) {
    return configCatStorage
  }

  if (pathname === '/balance') {
    return configCatBalance
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
