import { useEffect, useState } from 'react'

export interface SafeImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  fallbackLabel?: string
}

export default function SafeImage({
  src,
  fallbackLabel = '照片暂时无法显示',
  ...imgProps
}: SafeImageProps) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [src])
  if (failed) {
    return <div className="image-fallback" role="img" aria-label={fallbackLabel} />
  }
  return <img {...imgProps} src={src} onError={() => setFailed(true)} />
}
