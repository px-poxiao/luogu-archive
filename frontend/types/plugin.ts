export interface PluginTag {
  id: number
  name: string
  is_active?: boolean
  sort_order?: number
}

export interface PluginSnapshot {
  summary: string
  version: string
  code: string
  download_filename: string
  user_request_level: number
  user_request_analysis: string
  tag_ids: number[]
  runtime_mode: string
  supports_desktop: boolean
  supports_mobile: boolean
  last_verified_on: string
  admin_request_level?: number | null
  admin_request_analysis?: string | null
}

export interface PluginVersion {
  id: number
  version: string
  code: string
  code_sha256: string
  download_filename: string
  user_request_level: number
  user_request_analysis: string
  admin_request_level: number | null
  admin_request_analysis: string | null
  final_request_level: number
  runtime_mode: string
  supports_desktop: boolean
  supports_mobile: boolean
  last_verified_on: string
  published_at: string
}

export interface PluginDetail {
  id?: number
  article_id: string
  name?: string
  summary?: string
  is_official?: boolean
  is_recommended?: boolean
  is_listed: boolean
  down_reason?: string | null
  is_owner: boolean
  pending_only: boolean
  tags: PluginTag[]
  current: PluginVersion | null
  versions: Array<{
    id: number
    version: string
    published_at: string
    is_current: boolean
  }>
  pending_application: {
    id: number
    type: string
    snapshot: PluginSnapshot
    tags: PluginTag[]
  } | null
}

export function emptyPluginSnapshot(): PluginSnapshot {
  return {
    summary: '',
    version: '',
    code: '',
    download_filename: 'plugin.user.js',
    user_request_level: 0,
    user_request_analysis: '',
    tag_ids: [],
    runtime_mode: 'userscript',
    supports_desktop: true,
    supports_mobile: false,
    last_verified_on: new Date().toISOString().slice(0, 10),
    admin_request_level: null,
    admin_request_analysis: null,
  }
}
