import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { UploadCloud, FileVideo, X } from 'lucide-react'

const MAX_SIZE_BYTES = 100 * 1024 * 1024 // 100 MB

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function VideoUploader({ file, onFile, uploadProgress }) {
  const onDrop = useCallback(
    (accepted, rejected) => {
      if (rejected.length > 0) {
        const err = rejected[0].errors[0]
        if (err.code === 'file-too-large') {
          onFile(null, 'File exceeds 100 MB limit.')
        } else if (err.code === 'file-invalid-type') {
          onFile(null, 'Only MP4, MOV, or QuickTime videos are accepted.')
        } else {
          onFile(null, err.message)
        }
        return
      }
      if (accepted.length > 0) onFile(accepted[0], null)
    },
    [onFile],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/mp4': [], 'video/quicktime': [], 'video/x-msvideo': [] },
    maxSize: MAX_SIZE_BYTES,
    multiple: false,
    disabled: uploadProgress != null,
  })

  const clearFile = (e) => {
    e.stopPropagation()
    onFile(null, null)
  }

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={`relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors cursor-pointer
          ${isDragActive ? 'border-[#2D8653] bg-[#2D8653]/10' : 'border-gray-700 hover:border-gray-500'}
          ${uploadProgress != null ? 'pointer-events-none opacity-60' : ''}
        `}
      >
        <input {...getInputProps()} />

        {file ? (
          <>
            <FileVideo className="h-10 w-10 text-[#2D8653]" />
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white">{file.name}</span>
              <span className="text-xs text-gray-400">({formatBytes(file.size)})</span>
              {uploadProgress == null && (
                <button
                  type="button"
                  onClick={clearFile}
                  className="text-gray-500 hover:text-red-400 transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
            <p className="text-xs text-gray-500">Click or drag to replace</p>
          </>
        ) : (
          <>
            <UploadCloud className={`h-10 w-10 ${isDragActive ? 'text-[#2D8653]' : 'text-gray-500'}`} />
            <div>
              <p className="text-sm font-medium text-gray-200">
                {isDragActive ? 'Drop the video here' : 'Drag & drop your video here'}
              </p>
              <p className="mt-1 text-xs text-gray-500">MP4 or MOV, up to 100 MB</p>
            </div>
            <button
              type="button"
              className="mt-1 rounded-lg border border-gray-600 px-4 py-1.5 text-sm text-gray-300 hover:border-gray-400 hover:text-white transition-colors"
            >
              Browse files
            </button>
          </>
        )}
      </div>

      {/* Video preview */}
      {file && (
        <video
          key={file.name}
          src={URL.createObjectURL(file)}
          controls
          className="w-full rounded-lg max-h-64 bg-black"
        />
      )}

      {/* Upload progress bar */}
      {uploadProgress != null && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-gray-400">
            <span>Uploading…</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-gray-800">
            <div
              className="h-1.5 rounded-full bg-[#2D8653] transition-all duration-200"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
