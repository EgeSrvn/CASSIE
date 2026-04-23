import { useEffect, useState } from 'react'
import { getAvailableVMs, VM } from '../services/jobService'

interface VmCapacitySectionProps {
  title?: string
  description?: string
  kicker?: string
}

const defaultTitle = 'Remaining partitions by VM'
const defaultDescription = 'Track how many concurrent job slots are still open on each execution partition before starting a run.'
const defaultKicker = 'Cluster Capacity'

const formatVmCpu = (cpuMillis: number) => `${(cpuMillis / 1000).toFixed(2)} cores`
const formatVmMemory = (memoryMib: number) => `${(memoryMib / 1024).toFixed(2)} GiB`
const formatVmStorage = (storageMib: number) => storageMib > 0 ? `${(storageMib / 1024).toFixed(2)} GiB` : 'Auto'

export default function VmCapacitySection({
  title = defaultTitle,
  description = defaultDescription,
  kicker = defaultKicker,
}: VmCapacitySectionProps) {
  const [vmSummaries, setVmSummaries] = useState<VM[]>([])
  const [loadingVmSummaries, setLoadingVmSummaries] = useState(true)
  const [vmSummaryError, setVmSummaryError] = useState('')

  useEffect(() => {
    let cancelled = false

    const loadVmSummaries = async () => {
      try {
        setLoadingVmSummaries(true)
        setVmSummaryError('')
        const summaries = await getAvailableVMs()
        if (!cancelled) {
          setVmSummaries(summaries)
        }
      } catch (error: any) {
        if (!cancelled) {
          console.error('Failed to load VM capacity summaries:', error)
          setVmSummaries([])
          setVmSummaryError(error.message || 'Failed to load VM capacity summaries')
        }
      } finally {
        if (!cancelled) {
          setLoadingVmSummaries(false)
        }
      }
    }

    void loadVmSummaries()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="dashboard-capacity-card">
      <div className="dashboard-capacity-header">
        <div>
          <p className="dashboard-capacity-kicker">{kicker}</p>
          <h2>{title}</h2>
        </div>
        <p>{description}</p>
      </div>

      {loadingVmSummaries ? (
        <p className="dashboard-capacity-copy">Loading VM availability...</p>
      ) : vmSummaryError ? (
        <p className="dashboard-capacity-copy warning">{vmSummaryError}</p>
      ) : vmSummaries.length === 0 ? (
        <p className="dashboard-capacity-copy">No VM partitions are available right now.</p>
      ) : (
        <div className="dashboard-capacity-grid">
          {vmSummaries.map((vm) => (
            <article key={vm.name} className="dashboard-capacity-panel">
              <div className="dashboard-capacity-panel-head">
                <strong>{vm.display_name}</strong>
                <span>{vm.available_job_slots}/{vm.max_jobs} partitions remaining</span>
              </div>
              <div className="dashboard-capacity-stats">
                <span>CPU: {formatVmCpu(vm.available_cpu_millis)}</span>
                <span>Memory: {formatVmMemory(vm.available_memory_mib)}</span>
                <span>Storage: {formatVmStorage(vm.available_storage_mib)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
